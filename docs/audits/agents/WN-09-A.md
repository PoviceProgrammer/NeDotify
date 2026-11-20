## AREA WN-09 — Bridge lyrics, cover fetch, home feed, artist profile, waveform — ROLE A

### 1. Scope reviewed

**Files opened (path: line ranges actually read)**

- `core/api.py` — L3192–3595 (the assigned range, in full), plus L95–224 (SSRF guard
  `_is_ssrf_safe_url` / `_dns_resolves_to_public_ip`), L330–529 (`AppApi.__init__`,
  `_install_bridge_error_logging`, `_offline_bridge_result`), L1155–1214
  (`_enrich_track_lufs`, `_on_track_changed`), L2513–2552 (`get_playlists`),
  L3156–3171 (`get_wrapped_stats`, adjacent, out of range)
- `services/lyrics_service.py` — L1–327 (full)
- `services/lyrics_lookup.py` — L1–387 (full)
- `services/lyrics_cache.py` — L1–109 (full)
- `services/artist_service.py` — L84–113, L320–388 (`_best_thumbnail`, `get_avatars`,
  `get_profile`)
- `services/catalog_service.py` — L1–179 (`_cached`, `_artist_candidates`,
  `resolve_artist`, `preview_artists`)
- `services/recommendation_service.py` — L20–64, L170–219, L232–450, L478–517,
  L545–674, L895–917
- `services/youtube_service.py` — L293–347 (`_get_ydl_opts`), L858–927
  (`get_track_metadata`)
- `services/soundcloud_service.py` — L173–232 (`_get_client_id`, `_api_get`),
  L493–524 (`get_track_metadata`), L1000–1055 (`get_waveform_data_sync`)
- `services/base_service.py` — L75–174 (`submit`, `_join_request`)
- `core/database.py` — L213–252 (tracks schema), L1205–1244, L1595–1734
  (`get_history`, `get_tracks_missing_cover`, `backfill_track_metadata`,
  `get_most_played`, `get_top_artists`), L1940–1969, L2275–2314
- `utils/tag_parser.py` — L1–60, L118–167 (`extract_embedded_lyrics`)
- `ui/web_new_v2/js/lyrics.js` — L1–1225 (full)
- `ui/web_new_v2/js/home.js` — L1–1049 (full)
- `ui/web_new_v2/js/home-shell.js` — L1–70
- `ui/web_new_v2/js/profile.js` — L1–188 (full)
- `ui/web_new_v2/js/artist_profile.js` — L120–259
- `ui/web_new_v2/js/events.js` — L100–399
- `ui/web_new_v2/js/player.js` — L1710–1749, L2185–2414
- `ui/web_new_v2/js/search-discovery.js` — L100–127
- `ui/web_new_v2/js/main.js` — L120–179
- `ui/web_new_v2/js/utils.js` — L522–571, L615–674
- `ui/web_new_v2/index.html` — L283 (`#home-authentic-feed`)
- `.venv_win/Lib/site-packages/webview/util.py` — L234–333 (pywebview bridge threading model)
- `tests/conftest.py` — L1–176; `tests/test_verified_lyrics.py` L120–174;
  `tests/test_recommendation_bridge.py` L1–99

**Callees traced into other areas (defects there belong to those areas)**

- WN-22 Lyrics: `services/lyrics_service.py` (`translate_lyrics`, `get_lyrics`),
  `services/lyrics_lookup.py` (`accept`, `get`, providers), `services/lyrics_cache.py`
- WN-23 Recommendations: `services/recommendation_service.py` (`get_charts`,
  `get_feed`, `get_wave_for_track`, `get_recommendations`, `CURATED_WELCOME_TRACKS`),
  `services/taste_profile.py` (only via `_profile`)
- WN-24 Catalog/artist: `services/catalog_service.py` (`resolve_artist`),
  `services/artist_service.py` (`get_avatars`, `get_profile`)
- WN-12 SQLite: `core/database.py` (`get_history`, `get_tracks_missing_cover`,
  `backfill_track_metadata`, `get_most_played`, `get_top_artists`,
  `get_total_listening_time`)
- WN-25 LUFS: `services/lufs_scanner.py` (only as the writer of `lufs` /
  `loudness_lufs` consumed by `_enrich_track_lufs`)
- WN-19/WN-20 providers: `services/youtube_service.py::get_track_metadata`,
  `services/soundcloud_service.py::get_track_metadata`,
  `services/soundcloud_service.py::get_waveform_data_sync`
- WN-27 utils: `utils/tag_parser.py::extract_embedded_lyrics`

**Scratch probes (written under `%TEMP%`, nothing in the repo was modified)**

`%TEMP%\opencode\wn09_probe.py`, `wn09_probe2.py`, `wn09_probe3.py` — build a real
`AppApi` over a throwaway `DatabaseManager` and exercise the bridge methods with
stubs. Probe letters are referenced from the findings below.

---

### 2. Findings

#### F-WN-09-1  [P2] — `get_recommendations` returns `[]` for every provider slower than 3 s

- **File:** `core/api.py:3537-3553` (timeout at `core/api.py:3550`);
  provider budget in `services/recommendation_service.py:366-389`
- **Confirmed:** yes
- **Description:** `get_recommendations` is a synchronous bridge call that waits on an
  event for a fixed 3 s and then returns whatever the callback collected. The
  recommendation provider needs far longer than that: `_collect_uncached_candidates`
  waits up to 8 s for its provider futures and has a 12 s overall deadline. The
  callback therefore arrives after the bridge has already given up, and the method
  returns an empty list.
- **Cause:** the caller's deadline (3.0 s) is an order of magnitude smaller than the
  callee's own budget (8 s wait / 12 s deadline), and there is no cancellation of the
  already-submitted executor task, so the result is simply discarded.
- **Trigger conditions:** any invocation where the provider takes > 3 s — i.e. the
  normal case with a cold cache and any live network.
- **User impact:** the method returns `[]` even though the recommendation succeeds
  moments later. The already-paid-for work is thrown away. (No UI caller today — see
  F-WN-09-10 — so the visible impact today is limited to API/plugin consumers.)
- **Evidence:**
  ```python
  # core/api.py:3545-3553
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
  ```python
  # services/recommendation_service.py:388-389
  futures = [self._candidate_executor.submit(work) for _, _, work in jobs]
  done, pending = wait(futures, timeout=min(8.0, max(0, deadline - time.monotonic()))) if futures else (set(), set())
  ```
- **Reproduction / verification:** probe 4 — a provider that calls back after 6 s:
  `returned [] after 3.01s (timeout is 3.0s)`.
- **Suggested fix:** either make the bridge method asynchronous (return a
  `request_id` and deliver through an event, like `get_track_wave`), or raise the
  wait to at least the callee's budget (12 s) and cancel/ignore the late result.
- **Fix side effects:** a longer synchronous wait ties up a pywebview bridge thread
  for up to 12 s (the UI thread is *not* blocked — pywebview runs every API call on
  its own thread, `webview/util.py:308`), but the frontend still sees a late
  promise; an async redesign changes the return contract.
- **Discovered by:** A

---

#### F-WN-09-2  [P2] — `fetch_missing_covers` batch is permanently monopolised by rows that can never be resolved

- **File:** `core/api.py:3227-3265`; selection query `core/database.py:1626-1655`
  (`ORDER BY id DESC` / `LIMIT ?` at `core/database.py:1650-1651`)
- **Confirmed:** yes
- **Description:** the backfill picks the newest N rows that still lack artwork and
  re-resolves them on every pass. A row whose provider lookup keeps failing (deleted
  video, geo-block, yt-dlp breakage) never leaves the result set, so the *same* newest
  N rows are retried forever and the older qualifying rows are never attempted.
  There is also no rate limit and no delay between provider calls: each YouTube row
  triggers a full `yt_dlp.YoutubeDL(...).extract_info()` with a fresh `YoutubeDL`
  instance (`services/youtube_service.py:877-881`), i.e. one complete watch-page
  extraction per row, up to 40 of them in one pass.
- **Cause:** `get_tracks_missing_cover` has no attempt counter, no failure marker and
  no ordering that varies with failure; `fetch_missing_covers` has no backoff and no
  per-row budget.
- **Trigger conditions:** a library that contains at least `limit` rows whose
  provider metadata can no longer be resolved — deleted/removed YouTube videos are
  routine.
- **User impact:** the artwork backfill silently stops working for the whole backlog;
  the home grid keeps showing placeholder tiles for older rows, while the bridge
  burns a full yt-dlp extraction per failing row every 5 minutes (`ui/web_new_v2/js/home.js:93-96`
  throttles `fetch_missing_covers(40)` to once per 5 min) and risks YouTube
  rate-limiting the whole app.
- **Evidence:**
  ```python
  # core/api.py:3242-3251
  for row in rows:
      source = (row.get("source") or "").lower()
      source_id = str(row.get("source_id") or "").strip()
      if not source or not source_id:
          continue
      try:
          extra = self._resolve_track_metadata(source, source_id)
      except Exception:
          logger.debug("fetch_missing_covers: %s/%s failed", source, source_id, exc_info=True)
          continue
  ```
  ```sql
  -- core/database.py:1640-1652
  SELECT id, source, source_id FROM tracks
  WHERE ( (cover_path IS NULL AND (cover_url IS NULL OR cover_url = ''))
       OR title IS NULL OR title IN ('', 'Unknown', 'Unknown Title')
       OR artist IS NULL OR artist IN ('', 'Unknown', 'Unknown Artist') )
    AND source IS NOT NULL AND source != 'local'
    AND source_id IS NOT NULL AND source_id != ''
  ORDER BY id DESC
  LIMIT ?
  ```
- **Reproduction / verification:** probe F — 45 qualifying rows inserted, the
  provider made to fail for the newest 40:
  ```
  pass 1: {'updated': 0, 'scanned': 40}  provider calls: 40
  pass 2: {'updated': 0, 'scanned': 40}  provider calls: 40
  oldest rows ever attempted? False
  rows still missing cover: 45
  ```
  The 5 oldest rows were never contacted by the provider in either pass.
- **Suggested fix:** record a failure/attempt marker (or a `last_attempt_at`) per row
  and exclude recently-failed rows from the selection, plus add a small inter-request
  delay and a per-pass time budget.
- **Fix side effects:** the attempt marker requires a schema change in
  `core/database.py` (WN-12) and a migration; delaying requests lengthens the
  already-slow pass.
- **Discovered by:** A

---

#### F-WN-09-3  [P2] — `get_artists_avatars` never emits `artists_avatars_ready` when the service task raises, and resolves the whole batch sequentially

- **File:** `core/api.py:3515-3535`; service task `services/artist_service.py:329-339`;
  per-name budget `services/catalog_service.py:103-151`
- **Confirmed:** yes
- **Description:** two defects in one method. (a) `artist_service.get_avatars` runs its
  work in a pooled task with **no** `try/except`; the api's `try/except` only covers
  the *synchronous* `svc.get_avatars(...)` call, so an exception raised inside the task
  is swallowed by the executor and the callback never runs — no
  `artists_avatars_ready` event is ever emitted. (b) The batch resolves names
  **one at a time** (`catalog.resolve_artist` per name, each with its own 8 s
  deadline) and calls the callback only after the last name, so the UI waits for the
  slowest name in the batch.
- **Cause:** the callback-based error contract is implemented only on the submission
  path, not inside the worker; and the per-name resolution is serial instead of
  batched or parallel.
- **Trigger conditions:** (a) any exception inside `catalog.resolve_artist` /
  `_best_thumbnail`; (b) the normal case — the home feed asks for up to 30 names, each
  needing a YouTube Music artist search.
- **User impact:** the artist photo silently never appears. `ui/web_new_v2/js/artist_profile.js:209`
  (`fetchArtistAvatarFromApi`, 5 s timeout) shows the silhouette placeholder, and
  `ui/web_new_v2/js/home.js:622` releases its inflight marker only after 15 s — so a
  batch that takes longer than 15 s produces a duplicate request for the same names.
- **Evidence:**
  ```python
  # core/api.py:3530-3535
  try:
      svc.get_avatars([n for n in names if isinstance(n, str)][:30], callback=_done)
  except Exception as exc:
      logger.warning("get_artists_avatars failed: %s", exc)
      return {"status": "error", "error": str(exc)}
  return {"status": "loading"}
  ```
  ```python
  # services/artist_service.py:329-339
  def get_avatars(self, names, callback=None):
      def task():
          mapping = {}
          for name in list(dict.fromkeys(n.strip() for n in names or [] if isinstance(n, str) and n.strip()))[:30]:
              resolved = self.catalog.resolve_artist(name)
              raw = resolved.get('profile_data') or {}
              mapping[name] = self._best_thumbnail(raw) if resolved.get('status') == 'found' and resolved.get('source') == 'youtube' else ''
          if callback:
              callback(mapping)
      if self.submit(task) is None and callback:
          callback({})
  ```
- **Reproduction / verification:** probe E — a catalogue stub that raises:
  ```
  api return: {'status': 'loading'}
  events after 1s: []   <-- empty means the frontend waits for its timeout
  ```
- **Suggested fix:** wrap the service task body in `try/except` and always invoke the
  callback (empty map on failure); parallelise or batch the per-name resolution and
  emit incrementally.
- **Fix side effects:** always emitting a map changes the "resolved" semantics for
  consumers (`home.js:632` skips empty URLs, `artist_profile.js:234` resolves `null` —
  both already tolerate an empty value).
- **Discovered by:** A

---

#### F-WN-09-4  [P2] — `get_popular_tracks` still serves the hard-coded "fake charts" its own docstring says were removed, and `region` is a no-op

- **File:** `core/api.py:3315-3335` (docstring `core/api.py:3318-3322`);
  root cause in `services/recommendation_service.py:568-624`
  (country ignored at `:572`, curated fallback at `:618-619`)
- **Confirmed:** yes
- **Description:** the method's docstring asserts that the hard-coded
  *"Blinding Lights / Levitating …"* fallback was removed because it "presented fake
  charts to new users". The callee still does exactly that: `get_charts` falls back to
  `CURATED_WELCOME_TRACKS` when Last.fm and the local library are empty, and that
  constant is literally that list (`services/recommendation_service.py:26-35`). In
  addition `get_charts(country=...)` never reads `country` — it always returns the
  global Last.fm top tracks — so the `region` parameter of `get_popular_tracks` has
  **no observable effect whatsoever**.
- **Cause:** the caller-side contract (docstring + the `region` parameter) and the
  callee implementation disagree; the parameter is passed correctly but is ignored
  downstream.
- **Trigger conditions:** every call — the curated list appears whenever Last.fm has
  no chart and the local library is empty (i.e. every new user, and every user whose
  provider is unreachable).
- **User impact:** the "Популярное" section shows eight hard-coded Western pop
  tracks presented as a chart, with a Russian-user `region` of no effect — exactly the
  behaviour the docstring claims is gone.
- **Evidence:**
  ```python
  # core/api.py:3318-3322 (docstring)
  With no local listening history and no chart provider response the UI
  receives an empty list and shows its own empty state. The old hardcoded
  "Blinding Lights / Levitating ..." fallback presented fake charts to new
  users, which looked like real recommendations.
  ```
  ```python
  # services/recommendation_service.py:572 and :618-619
  chart_raw = self.lastfm.chart.getTopTracks(limit=max_results * 2) if hasattr(self, 'lastfm') and self.lastfm else []
  ...
              if not tracks:
                  tracks = CURATED_WELCOME_TRACKS[:max_results]
  ```
- **Reproduction / verification:** probe G — `get_charts(country="JP")` with no
  Last.fm and an empty library:
  ```
  charts returned: ['Blinding Lights', 'Levitating', 'Love The Way You Lie', 'Bohemian Rhapsody'] ... total 8
  is CURATED_WELCOME_TRACKS used? True
  ```
  probe H — `api.get_popular_tracks("JP")`:
  ```
  country arg seen by get_charts: ['JP']
  emitted titles: ['Blinding Lights', 'Levitating', 'Love The Way You Lie', 'Bohemian Rhapsody']
  ```
- **Suggested fix:** decide the intended behaviour and make both sides agree — either
  drop the curated fallback in the service and fix the docstring, or keep it and
  correct the docstring; and either honour `country` in `get_charts` or remove the
  `region` parameter from the bridge method.
- **Fix side effects:** removing the curated fallback leaves the popular section
  empty for new users, which is a product decision, not a code change. The
  country-ignoring implementation and the curated constant live in
  `services/recommendation_service.py` → **root cause owned by WN-23**; the
  WN-09-side defect is the false contract in the docstring and the no-op parameter.
- **Discovered by:** A

---

#### F-WN-09-5  [P2] — `get_waveform` fetches a client-supplied URL with no SSRF validation

- **File:** `core/api.py:3583-3593`; guard available at `core/api.py:161`
  (`_is_ssrf_safe_url`), used elsewhere in the same file at `core/api.py:1111` and
  `core/api.py:2365`
- **Confirmed:** yes
- **Description:** `get_waveform` reads `waveform_url` straight out of the dict the
  frontend passed and hands it to the SoundCloud service, which performs
  `self._session.get(json_url, timeout=10.0)` with **no** scheme/host validation
  (`services/soundcloud_service.py:1018-1053`). The same file already has an SSRF
  guard used for the other two client-supplied URLs.
- **Cause:** the bridge method trusts a field of a client-provided payload; the
  existing `_is_ssrf_safe_url` helper is not applied on this path.
- **Trigger conditions:** any call to `window.pywebview.api.get_waveform({waveform_url:
  "<any url>"})` from the WebView.
- **User impact:** the backend can be induced to issue HTTP requests to loopback and
  private addresses (the app's own loopback proxy on `127.0.0.1:<PROXY_PORT>`, other
  LAN services) and to return their status/body-derived answer (the JSON is parsed
  and only the sample array is returned, so the leak is limited to reachability and
  timing, not raw content).
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
  # services/soundcloud_service.py:1032
  r = self._session.get(json_url, timeout=10.0)
  ```
- **Reproduction / verification:** probe 7 —
  `api.get_waveform({"title": "x", "waveform_url": "http://127.0.0.1:9/x.json"})`
  reached the service, and the service fetched that exact URL
  (`urls fetched by service: ['http://127.0.0.1:9/x.json']`).
- **Suggested fix:** validate `waveform_url` with `_is_ssrf_safe_url` before use, and
  preferably restrict it to the expected SoundCloud CDN hosts
  (`sndcdn.com` / `api-v2.soundcloud.com`).
- **Fix side effects:** a host allow-list is the safer option; a generic
  `_is_ssrf_safe_url` check still permits arbitrary public hosts, which is
  acceptable given the URL is only used to fetch a JSON sample array.
- **Discovered by:** A

---

#### F-WN-09-6  [P2] — `get_lyrics_translation` silently returns the untranslated original text when the translation service is unreachable

- **File:** `core/api.py:3286-3291`; callee `services/lyrics_service.py:243-272`;
  consumer `ui/web_new_v2/js/lyrics.js:63-83`
- **Confirmed:** yes
- **Description:** `translate_lyrics` catches every exception and returns the
  **input lyrics unchanged** (`services/lyrics_service.py:269-272`). The bridge's
  `except` branch that returns `{"error": ...}` is therefore almost dead code, and the
  method's return type is polymorphic — `str` on success, `dict` on the (rare)
  exception path. The frontend has to branch on `typeof res === 'string'` to build
  its line map.
- **Cause:** the callee converts a transport failure into a successful-looking
  result; the caller cannot distinguish "translated" from "not translated".
- **Trigger conditions:** Google Translate unreachable, rate-limited (HTTP 429), or
  the response shape not matching `data[0]` — all plausible for an unauthenticated
  `translate.googleapis.com` endpoint.
- **User impact:** the translation toggle switches on and stays "active" but the lyrics
  never change language. `js/lyrics.js:72-79` only maps a line when
  `transLines[i] !== k`, so an unchanged response yields an **empty** map and the user
  gets no translated text and no error message — and because the map stays empty,
  `toggleTranslation` re-issues the same failing request on every toggle.
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
  # services/lyrics_service.py:269-272
              return "\n".join(out) if out else lyrics
          except Exception as e:
              logger.debug(f"Translation error: {e}")
              return lyrics
  ```
- **Reproduction / verification:** probe 3 — `_open_url` forced to raise:
  ```
  translate_lyrics on network failure returns: 'line one\nline two'
  identical to input? True
  ```
  and with a raising stub service the bridge returns `{'error': 'boom'}` — i.e. two
  different shapes for "no translation".
- **Suggested fix:** make the failure explicit — have `translate_lyrics` signal
  failure (raise, or return a sentinel) and let the bridge return a single, stable
  shape; the frontend already handles a dict result.
- **Fix side effects:** changing the callee's return contract affects any other
  caller of `translate_lyrics` (the only one is this bridge method — grep confirmed);
  the frontend's `typeof res === 'string'` branch must stay for the success path.
- **Discovered by:** A

---

#### F-WN-09-7  [P3] — `get_lyrics` drops the service's final result whenever the service published any partial update

- **File:** `core/api.py:3208-3219` (guard at `core/api.py:3218-3219`);
  consumer `ui/web_new_v2/js/lyrics.js:894-909`
- **Confirmed:** yes (with the current `LyricsService` the user-visible effect is nil)
- **Description:** `run()` publishes the value the service *returned* only when
  nothing has been published yet. If the service streamed any `on_update` payload
  first — even a `phase='partial'` one — the returned final result is silently
  discarded and no `phase='final'` event is ever emitted.
- **Cause:** a single boolean (`published[0]`) is used both as "did we emit
  anything?" and as "may we still emit the final?", but the two are different
  questions.
- **Trigger conditions:** a lyrics service that streams a partial upgrade without
  also streaming a final one. Today's `LyricsService` always delivers the final
  through `on_update` (probe A shows `partial` rev 1 then `final` rev 2), so the
  current impact is latent.
- **User impact:** if it ever triggers, `js/lyrics.js:899` (`if (!data.request_id ||
  data.phase === 'final') pendingLyricsRequest = null;`) never clears the pending
  request, so the overlay stays "pending" for `LYRICS_PENDING_MAX_AGE_MS` (15 s) and
  the "Повторить" button is never offered; the plain→synced karaoke upgrade would
  never arrive.
- **Evidence:**
  ```python
  # core/api.py:3211-3219
  try:
      service = self._core.lyrics
      if 'on_update' in inspect.signature(service.get_lyrics).parameters:
          data = service.get_lyrics(track_name, artist_name, duration_ms=duration_ms, file_path=file_path,
                                    album_name=album_name, on_update=publish, is_current=current)
      else:
          data = service.get_lyrics(track_name, artist_name, duration_ms=duration_ms, file_path=file_path)
      if not published[0]:
          publish(dict(data or {}, revision=1, phase='final'))
  ```
- **Reproduction / verification:** probe 1, "found" case — a service that calls
  `on_update({'phase':'partial', ...})` and then returns the final result:
  ```
  found     events=[('lyrics_ready', {..., 'revision': 1, 'phase': 'partial', ...})]
  ```
  — a single partial event; the final payload the service returned was never published.
  Probe A (real `LyricsService`) shows two events (`partial` rev 1, `final` rev 2),
  confirming today's behaviour is unaffected.
- **Suggested fix:** track "a final was published" separately from "anything was
  published", and always emit a terminal `phase='final'` payload.
- **Fix side effects:** with today's service that would produce a duplicate final
  event (the service already emits one) and would shift the revision numbering that
  `js/lyrics.js:896` uses to drop out-of-order updates.
- **Discovered by:** A

---

#### F-WN-09-8  [P3] — `get_popular_tracks` fallback passes the region code as an artist name

- **File:** `core/api.py:3328-3331`; callee signature
  `services/recommendation_service.py:676`
- **Confirmed:** yes
- **Description:** when `get_charts` is absent, the fallback calls
  `get_releases([region], callback=...)`. `get_releases`' first parameter is
  `favorite_artists` — a list of artist names — so the region code `"JP"` /
  `"US"` is submitted as if it were an artist.
- **Cause:** the fallback was written against the wrong callee signature.
- **Trigger conditions:** only if `get_charts` disappears from
  `self._core.recommendations` (or is renamed) — the branch is dead code today.
- **User impact:** none today; if the branch ever activates, the popular section
  would resolve releases for an artist literally named "US".
- **Evidence:**
  ```python
  # core/api.py:3328-3331
              else:
                  self._core.recommendations.get_releases(
                      [region], callback=lambda tracks: self._emit("popular_results", tracks or [])
                  )
  ```
  ```python
  # services/recommendation_service.py:676
  def get_releases(self, favorite_artists=None, max_results=10, callback=None, error_callback=None):
  ```
- **Reproduction / verification:** probe 5, "no-get_charts fallback" branch:
  ```
  no-get_charts fallback calls: [('get_releases-fallback', ['JP'], 10)]
  ```
- **Suggested fix:** drop the dead branch, or pass actual artist names
  (`db.get_top_artists`) the way `get_home_releases` does
  (`core/api.py:3765`, tested in `tests/test_recommendation_bridge.py:55-65`).
- **Fix side effects:** none.
- **Discovered by:** A

---

#### F-WN-09-9  [P3] — `get_artist_profile` silently re-calls the service without `artist_ref`/`is_current` when the service body raises `TypeError`

- **File:** `core/api.py:3509-3512`; callee `services/artist_service.py:341-388`
- **Confirmed:** yes (code-path analysis; not observed at runtime)
- **Description:** the `except TypeError` is meant to support a service whose
  `get_profile` lacks the newer `artist_ref`/`is_current` keywords. But it also
  catches a `TypeError` raised **inside** the service body, and then re-invokes
  `get_profile` with a reduced signature — losing the artist's source binding
  (`artist_ref`) and the staleness guard (`is_current`) — and paying for the whole
  catalogue lookup twice.
- **Cause:** a signature-compatibility shim implemented as a broad `except` around the
  call rather than as an `inspect.signature` check.
- **Trigger conditions:** any `TypeError` raised inside `artist_service.get_profile`
  or inside `catalog_service.resolve_artist`.
- **User impact:** the profile resolves against a *different* identity (the
  catalogue re-searches by name instead of using the bound `source_id`), the
  supersede guard is lost so a stale profile can overwrite a newer one, and the
  expensive lookup runs twice.
- **Evidence:**
  ```python
  # core/api.py:3509-3513
  try:
      svc.get_profile(name, callback=ok, error_callback=fail, artist_ref=artist_ref, is_current=current)
  except TypeError:
      svc.get_profile(name, callback=ok, error_callback=fail)
  return {'status': 'loading', 'artist': name, 'request_id': rid}
  ```
- **Reproduction / verification:** not observed at runtime — a `TypeError` must be
  raised inside `artist_service.get_profile`'s task body (the current implementation
  wraps its risky part in `try/except`, so the window is narrow). Verification would
  be: stub `svc.get_profile` to raise `TypeError` on the first call and record the
  kwargs of both calls — the second call must be shown to lack `artist_ref`.
- **Suggested fix:** detect the accepted signature once
  (`inspect.signature(svc.get_profile).parameters`) and branch on that instead of
  catching `TypeError`.
- **Fix side effects:** none — the signature check is deterministic.
- **Discovered by:** A

---

#### F-WN-09-10  [P2] — `get_authentic_home_feed` and `api.get_recommendations` have no frontend caller: the "authentic home feed" feature does not exist in the running app

- **File:** `core/api.py:3337-3386` and `core/api.py:3537-3553`;
  UI `ui/web_new_v2/index.html:283`, `ui/web_new_v2/js/events.js:139-143`,
  `ui/web_new_v2/js/home.js:292-431`; documentation
  `ui/web_new_v2/UI_UX_CURRENT_STATE.md:31`
- **Confirmed:** yes
- **Description:** a grep of the whole `ui/web_new_v2` tree finds **no** call to
  `window.pywebview.api.get_authentic_home_feed(...)` and **no** call to
  `window.pywebview.api.get_recommendations(...)`. The UI side of the contract
  exists (`events.js:139` handles `authentic_home_ready`, `home.js:292
  renderAuthenticHome` renders it) but nothing ever asks for the data, and
  `index.html:283` keeps `#home-authentic-feed` at `style="display:none"` (which
  `renderAuthenticHome` never clears).
- **Cause:** the producer and the consumer were wired on different sides and the
  wiring was never completed.
- **Trigger conditions:** always — the section is simply never populated.
- **User impact:** the "динамический контейнер аутентичной ленты рекомендаций" that
  `UI_UX_CURRENT_STATE.md:31` documents does not appear in the app. It also means the
  defect in F-WN-09-1 is invisible in the UI, and that `get_authentic_home_feed`'s
  error handling, `_format_section_items` and `_enrich_track_lufs` integration are
  untested by the shipped UI.
- **Evidence:**
  ```python
  # core/api.py:3337-3338
  def get_authentic_home_feed(self, limit: int = 20):
      """Emit authentic home recommendations based on history & taste profile."""
  ```
  ```html
  <!-- ui/web_new_v2/index.html:283 -->
  <div id="home-authentic-feed" style="display:none; width:100%; flex-direction:column; gap:24px;"></div>
  ```
- **Reproduction / verification:** `rg "get_authentic_home_feed|api\.get_recommendations"
  ui/web_new_v2` → no matches (only `api.get_recommendations` in Python and in
  `tests/`); `rg "authentic" ui/web_new_v2` → the seven matches listed above, none of
  which issues the request.
- **Suggested fix:** either wire the UI (call `get_authentic_home_feed` when the home
  page loads and unhide the container) or remove the dead bridge method, the event
  handler and the container so the contract is not documented as existing.
- **Fix side effects:** wiring it up turns on a second recommendation source on the
  home page (extra provider traffic); removing it removes a documented feature.
- **Discovered by:** A

---

### 3. Clean areas

Checked and found correct:

- **`get_lyrics` request-id round-trip.** The frontend really sends it
  (`ui/web_new_v2/js/lyrics.js:854`,
  `window.pywebview.api.get_lyrics(track.title, track.artist, durMs, track.file_path, track.album || '', activeLyricsRequestId)`),
  the backend echoes it (`core/api.py:3206`), and the frontend filters on it
  (`js/lyrics.js:314`, `js/lyrics.js:896`). Stale responses really are discarded:
  probe B issued two requests for the same track and only the **newer** one produced
  events — the older `request_id` produced nothing, because the backend's
  `_lyrics_cascade_count` gate (`core/api.py:3196-3201`) plus the frontend's
  `request_id` check both reject it. The backend's staleness gate is the cascade
  counter rather than the `request_id`, but the two mechanisms agree.
- **`get_lyrics` "no lyrics" handling.** `not_found` (looked up, nothing there),
  `unavailable` (providers failed) and `found` are three distinct `status` values
  that reach the UI intact (probe 1 / probe D), and `js/lyrics.js:928-936` renders a
  different message for each, including a "Повторить" button for the non-instrumental
  empty states. The UI can distinguish "not found" from "temporarily unavailable".
- **`get_lyrics` payload completeness.** Probe A shows the event payload carries
  `status, syncedLyrics, plainLyrics, instrumental, weight, source, match_type,
  matched_title, matched_artist, matched_duration, confidence, revision, phase,
  request_id` — the UI consumes `syncedLyrics`, `plainLyrics`, `instrumental`,
  `status`, `source`, `match_type` and `phase`; nothing it needs is missing.
- **No HTML injection through lyrics or translations.** Every lyric line and every
  translated line is written with `textContent`
  (`js/lyrics.js:953`, `:959`, `:1009`, `:1013`); the only `innerHTML` in the lyrics
  view interpolates fixed strings (`js/lyrics.js:933`, `:1002`).
- **`get_profile_stats` / `get_home_data` payload shapes match the UI exactly.**
  Probe 8: `get_home_data` → `{analytics, favorites_count, history, playlists,
  total_listening_ms, total_tracks}`, consumed by `js/home.js:118-134`,
  `js/home-shell.js:11-14` and `js/home.js:225-254`; `get_profile_stats` →
  `{favorite_count, most_played, playlist_count, recently_played,
  total_listening_time_ms, total_tracks}`, consumed by `js/profile.js:138-148`
  (`recently_played` → `recent`, `most_played` → `renderTop`). Every field name the
  frontend reads exists, and the row shapes support it (`get_most_played` returns
  `play_count`, `get_history` returns `track_id` + `played_at`).
- **`get_home_data` empty state / no provider coupling.** It touches only local
  SQLite; an empty library yields `history: []`, `favorites_count: 0`, empty
  `analytics.top_tracks/top_artists`, and the frontend renders its own empty states
  (`js/home.js:260`, `:694`, `:815`, `:852`).
- **`get_authentic_home_feed` failure isolation.** The provider error callback emits
  `authentic_home_ready` with `{"sections": []}` rather than hanging
  (probe 10), and the outer `try/except` covers the DB read as well.
- **`get_track_wave` honours `exclude_ids` and `request_id`.** `exclude_ids` is
  forwarded (`core/api.py:3574`) and matched against the candidate's `id`/`source_id`
  (`services/recommendation_service.py:239`, `:279-284`); the seed itself is always
  excluded. `request_id` is echoed in the payload (`core/api.py:3563-3564`) and the
  frontend drops a replaced wave on it (`js/main.js:129`). An invalid seed still
  completes the event instead of leaving the listener waiting
  (`core/api.py:3569-3571`, pinned by `tests/test_recommendation_bridge.py:94-99`).
- **`get_waveform` determinism, caching and array length.** The peak array is
  deterministic for a given waveform JSON and cached by the SoundCloud service
  (`services/soundcloud_service.py:1027-1028`, `:1050`); the returned length is
  variable (100 after resampling, the raw length when shorter) and the frontend
  interpolates by normalised position (`js/player.js:2379-2384`), so no fixed length
  is required. A track without `waveform_url` yields `[]` and the frontend falls
  back to a deterministic pseudo-waveform (`js/player.js:2277`, `:2286-2294`) — no
  crash, no missing-audio-file path.
- **`fetch_missing_covers` does not download cover files to disk.** It only stores
  the provider URL in the DB, so the "filename derived from an unsanitised URL" risk
  does not exist on this path. Per-row failures are non-fatal and the loop does not
  stop early (`core/api.py:3247-3262`), and `backfill_track_metadata` refuses to
  overwrite real titles/artists with placeholders (`core/database.py:1674-1687`).
  Probe 9 confirmed the write path: `{'title': 'Real Title', 'artist': 'Real Artist',
  'cover_url': 'http://c/x.jpg'}`.
- **`get_artists_avatars` key shape.** The returned map is keyed by the *trimmed*
  name, exactly as the frontend produces it (`js/home.js:601` trims before sending,
  `js/artist_profile.js:210` trims too), and a name containing a comma is **not**
  split — it is searched as one string and simply resolves to `''` (probe C:
  `{'Adele': 'http://img/Adele', 'A,B': ''}`). Duplicate names are collapsed by the
  service. Both consumers match the key case-insensitively/by trimmed title.
- **Offline interception covers this area.** `_offline_bridge_result`
  (`core/api.py:461-512`) short-circuits `get_popular_tracks`,
  `get_authentic_home_feed`, `get_artists_avatars`, `fetch_missing_covers`,
  `get_lyrics_translation`, `get_track_wave` and `get_artist_profile` with a
  well-formed payload, so no method in this area hangs offline. `get_lyrics` is not
  intercepted but the lyrics service itself detects offline mode
  (`services/lyrics_lookup.py:74-75`, `:307`) and reports `unavailable`.
- **`get_lyrics` duration handling.** The frontend's `durMs` heuristic
  (`js/lyrics.js:786`) and the lookup's 1 % synced-lyrics duration window
  (`services/lyrics_lookup.py:61-62`) line up; `match_type: 'base'` is propagated so
  the UI can warn that a non-remix is showing without time codes
  (`js/lyrics.js:1001`).

---

### 4. Coverage gaps

- **No live-network verification.** All provider behaviour (yt-dlp extraction,
  Last.fm charts, LRCLIB/Netease/QQ/Genius/Megalobiz, Google Translate) was
  exercised only through stubs. The `network` pytest marker is deselected by
  `pytest.ini`, and the audit brief forbids touching the live profile, so the
  real-world latency assumptions behind F-WN-09-1 (3 s vs 8/12 s) and F-WN-09-2
  (per-row yt-dlp cost) are derived from the code, not measured. The probe
  timings confirm the *mechanism*, not the absolute numbers.
- **`get_wrapped_stats` (`core/api.py:3156`) is out of this range** (WN-08). The
  date-range/timezone question raised for "profile stats" therefore lands there:
  `get_profile_stats` itself is an all-time view with no date range, and the
  period-scoped numbers the profile page shows come from
  `core/database.py:1723-1734` (`datetime('now','-7 days')` — SQLite UTC, matching
  the UTC `CURRENT_TIMESTAMP` default of `history.played_at` at
  `core/database.py:277`). The *display* conversion to local time happens in
  `js/profile.js:21-34` (WN-32), which is where a UTC-vs-local day shift could
  appear for the "day/month/year" fallback format.
- **`services/lufs_scanner.py` was not re-reviewed** (WN-25). Only its contract
  with this area was checked: it writes `lufs` and `loudness_lufs`
  (`services/lufs_scanner.py:103`) and `_enrich_track_lufs`
  (`core/api.py:1161-1193`) reads exactly those two columns and propagates them
  under both names — consistent.
- **`services/taste_profile.py` was only traced through
  `recommendation_service._profile`** (WN-23). `UserTasteProfile.build_from_db` was
  not read line-by-line.
- **The Spotify/iTunes branches of `artist_service.get_profile`**
  (`services/artist_service.py:373-379`) were not exercised; the bridge path for
  them is the same as for YouTube, so the risk is confined to the callee (WN-24).
- **`core/api.py:3461-3513` (`_store_artist_binding`, `get_artist_profile`)** were
  read and traced into `js/artist_profile.js`, but the artist-profile *rendering*
  path was only partially followed (the candidate-preview flow at
  `core/api.py:3503-3508` → `services/catalog_service.py:153-166` was verified by
  reading, not by running).
- **The 30-name cap in `get_artists_avatars` (`core/api.py:3531`) vs the service's
  own cap (`services/artist_service.py:332`)** was checked for shape only. Because
  the api slices *before* de-duplication, a request whose first 30 entries contain
  duplicates or blanks resolves fewer than 30 distinct names; the frontend simply
  re-requests the rest after its 15 s window, so no data is lost — this was judged
  a non-defect and not raised as a finding.
