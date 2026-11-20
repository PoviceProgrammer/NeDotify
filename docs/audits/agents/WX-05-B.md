## AREA WX-05 — Search fan-out (`AppApi.search` → `BaseMusicService.submit` → providers → `track_resolver` → cache) — ROLE B

### 1. Scope reviewed

**Files opened (path: line ranges actually read):**

| File | Lines read |
|---|---|
| `docs/audits/WIN_AUDIT_CONTEXT.md` | 1–200 (full) |
| `docs/audits/WIN_AUDIT_AREAS.md` | 1–70 (full) |
| `core/api.py` | 1–140, 200–319, 340–519, 1122–1181, 1608–1757, 2000–2399, 3490–3529, 3640–3719, 4120–4169 |
| `services/base_service.py` | 1–329 (full) |
| `services/youtube_service.py` | 95–124, 180–329, 340–659, 1020–1089 |
| `services/soundcloud_service.py` | 1–100, 100–259, 250–499, 530–619 |
| `services/spotify_service.py` | 1–220 |
| `services/yandex_service.py` | 80–149 |
| `services/itunes_gateway.py` | 1–93 (full) |
| `services/recommendation_service.py` | 40–159, 320–549 |
| `services/catalog_service.py` | 30–189 |
| `services/lyrics_service.py` | 40–119, 170–249 |
| `services/lastfm_service.py` | 92–161 |
| `services/track_resolver.py` | 1–140 |
| `core/resolver.py` | 1–271 (full) |
| `core/app.py` | 180–259, 290–586 |
| `core/playback_recovery.py` | 40–179 |
| `core/database.py` | 1120–1169, 1345–1464 |
| `utils/search_query.py` | 1–101 (full) |
| `ui/web_new_v2/js/search.js` | 1–529, 1030–1109 |
| `ui/web_new_v2/js/events.js` | 110–169 |
| `ui/web_new_v2/index.html` | grep: 363–379, 1861, 2104, 2235 |
| `tests/test_api_search.py` | 1–75 (full) |
| `tests/test_provider_performance.py` | 1–102 (full) |
| `tests/conftest.py` | 1–140 |

**Callees traced into other areas (not owned by WX-05):**

- `services/track_resolver.py::TrackResolver` — own pool `_resolver_pool(8)`, own `_memo_lock`; **not** reached from the `AppApi.search` fan-out (the fan-out calls provider `search()` directly, not the resolver). Its `resolve_tracks` is used by the recommendation service, not by search.
- `core/database.py::search_tracks / search_albums / search_playlists` — owned by **WN-12**; the LIKE/FTS escaping there is correct (see §3).
- `core/resolver.py::StreamResolver` — owned by **WN-15**; not on the search path.
- `core/proxy.py` — not touched (not in the fan-out).
- `services/lyrics_service.py`, `services/lyrics_lookup.py` — owned by **WN-22**; they use their own pool (`_lyrics_pool`, 6) and their own instance lock, so they are **not** coupled to the search caches.
- `services/itunes_gateway.py` — owned by **WN-21**; it is on the search path (the "Spotify" provider) and it binds the **class-level** `BaseMusicService._cache_lock` as its `Condition` lock. Owned by WN-21, reported here because it is reached from the fan-out.
- `core/app.py::re_resolve_stream_url_async` — owned by **WN-05/WN-02**; reached from the PLAY path, not from search.

**Instrumented local probes** (scratch files under `%TEMP%\opencode\`, no repo file touched, no network):
`wx05_probe.py` (lock/cache identity, fan-out list), `wx05_probe2.py` (is the class lock held during network calls?), `wx05_probe3.py` (real `AppApi.search` wall-clock with stubbed providers), `wx05_probe4.py` (provider-pool coupling, late-answer truncation), `wx05_probe5.py` (payload sizes, cache bounds).

---

### 2. Findings

#### F-WX-05-1  [P1] — The provider thread pool is shared between search and playback stream extraction: a burst of searches stalls the PLAY button

- **File:** `services/youtube_service.py:195` + `:512` + `:1069`; `services/soundcloud_service.py:132` + `:402` + `:846`
- **Confirmed:** yes
- **Description:** Each provider owns exactly one `ThreadPoolExecutor`, and that pool serves **both** the best-effort search work and the user-visible playback extraction. There is no separate pool, no priority lane and no reservation.
- **Cause:** The pool is a per-instance attribute created in `__init__` and every asynchronous entry point submits to it. A search that is already known to be hopeless (the bridge already gave up on it) still occupies a worker for the full duration of the provider's network call, because the bridge's deadline only stops the *UI* from waiting — it never cancels the provider task.
- **Trigger conditions:** The user types a query with pauses long enough to fire the 200 ms debounce repeatedly (each pause = one full fan-out = one YouTube/SoundCloud/Spotify search), while the provider is slow or unreachable. Ten such searches saturate the pool. Clicking a result then has to queue behind them.
- **User impact:** The PLAY button appears to hang for tens of seconds before the track starts, with no error and no spinner change. The error surfaces only as "Не удалось найти поток" much later.
- **Evidence:**
  ```python
  # services/youtube_service.py:195
  self._executor = ThreadPoolExecutor(max_workers=10)
  # services/youtube_service.py:512  (search)
  self._executor.submit(_search)
  # services/youtube_service.py:1069 (playback stream extraction)
  self._executor.submit(_extract)
  ```
  ```python
  # services/soundcloud_service.py:132 / :402 / :846
  self._executor = ThreadPoolExecutor(max_workers=10)
  self._executor.submit(_search)     # search
  self._executor.submit(_extract)    # playback stream extraction
  ```
- **Reproduction / verification:** `wx05_probe4.py` fills a 10-worker pool with 10 stuck 12-second tasks (the YouTube pool size) and then submits the extraction task:
  ```
  extraction task submitted at +0.0s, started at +11.8s after 10 stuck searches
  ```
  In production the stuck search is bounded by the provider's own network timeouts, not by the bridge deadline: YouTube `TimeoutSession` forces `kwargs["timeout"] = 6` (`services/youtube_service.py:201-205`), while the SoundCloud yt-dlp fallback runs with `socket_timeout: 10, retries: 1, extractor_retries: 1` (`services/soundcloud_service.py:272-280`) → up to ~30–40 s of worker occupancy per stuck SoundCloud search, against a bridge deadline of only 8 s.
- **Suggested fix:** Split the pool per provider into a *search* pool and a *resolve* pool, or reserve a minimum number of workers for extraction (`ThreadPoolExecutor` has no priority lane, so a second pool is the honest fix). Alternatively give the playback path its own dedicated executor.
- **Fix side effects:** More threads (2 pools × 4 providers); the "at most 10 concurrent provider searches" back-pressure disappears, so a pathological typist can queue more provider work than before — a separate admission-control budget would be needed.
- **Discovered by:** B

---

#### F-WX-05-2  [P2] — A provider answer that arrives after the bridge deadline is silently discarded

- **File:** `core/api.py:2175-2208` (owner: **WN-06**)
- **Confirmed:** yes
- **Description:** The per-provider watchdog fires at 6 s (YouTube, Spotify) / 8 s (SoundCloud) and finalises the provider with an **empty** result list. A real answer that lands one second later is thrown away: `_finish()` returns early because `is_done[0]` is already `True`.
- **Cause:** The deadline is a UI-facing "stop waiting" timer, but it is implemented as "declare the provider finished and empty". There is no grace period and no late-result path, and the discarded answer is not cached either, so the next search pays the full network cost again.
- **Trigger conditions:** The provider answers between 6 s and its own internal timeout. This is a *normal* case on a slow link: the YouTube request timeout is exactly 6 s, so a request that takes 6.1 s lands in the dead zone.
- **User impact:** "Nothing found on YouTube" although YouTube answered a moment later. The user retypes and pays the cost again.
- **Evidence:**
  ```python
  # core/api.py:2199-2208
  def _on_timeout():
      with lock:
          if is_done[0]:
              return
      logger.warning("%s search timed out after %.1fs", name, _timeout)
      _finish([])          # <- finalises the provider with an EMPTY list
  ...
  timer = threading.Timer(_timeout, _on_timeout)
  ```
  ```python
  # core/api.py:2175-1787
  def _finish(tracks):
      with lock:
          if is_done[0]:
              return          # <- the late answer dies here
          is_done[0] = True
  ```
- **Reproduction / verification:** `wx05_probe4.py` case (b), real `AppApi.search` with all three providers answering at 7 s:
  ```
  search_results   at + 0.01s source=local     tracks=0
  search_results   at + 6.03s source=youtube   tracks=0     <- deadline fired, empty chunk
  search_results   at + 6.03s source=spotify   tracks=0     <- deadline fired, empty chunk
  search_results   at + 7.02s source=soundcloud tracks=1    <- 8s ceiling, survives
  search_completed at + 7.02s
  ```
  The YouTube and Spotify answers (which carry `tracks=1`) never reach the UI.
- **Suggested fix:** On timeout, emit the empty chunk but keep the slot open for a late answer; or raise the YouTube/Spotify deadline above the providers' own request timeout (YouTube's is 6 s, so the bridge deadline should be > 6 s, e.g. 8 s like SoundCloud) and make the deadline a *wait* limit rather than a *result* limit.
- **Fix side effects:** A longer deadline means the spinner stays up longer for a genuinely dead provider; the UI would need a "still trying" affordance to stay honest.
- **Discovered by:** B

---

#### F-WX-05-3  [P2] — No circuit breaker: a dead provider is re-queried on every search

- **File:** `services/spotify_service.py:141-145` and `:162-165`; `services/youtube_service.py:507-510`; `services/soundcloud_service.py:386-401`
- **Confirmed:** yes
- **Description:** A provider that is down (HTTP 5xx, DNS failure, timeout) is contacted again on the next search, and the next one after that. There is no failure counter, no open-circuit state and no exponential back-off for the search path. The only negative caching in the whole fan-out is incidental: Spotify caches **only non-empty** results, YouTube/SoundCloud cache the result list (possibly empty) but only when the request *succeeded*.
- **Cause:** The cache layer stores successful payloads; failures travel as `error_callback` and are dropped. The `_join_request` single-flight (`services/base_service.py:140-161`) only de-duplicates *concurrent* identical requests, not sequential ones.
- **Trigger conditions:** The user keeps searching (or keeps typing with pauses) while one provider is down. Because the UI debounce is 200 ms, "keeps searching" is easy to trigger.
- **User impact:** Continuous background traffic to a dead third party; on a metered or proxied connection this burns the user's bandwidth and the provider's quota. For Spotify/iTunes the requests also queue behind the gateway's global 3.5 s rate gate (`services/itunes_gateway.py:21, 57-63`), so each dead attempt also holds up the next legitimate one.
- **Evidence:**
  ```python
  # services/spotify_service.py:141-145
  if albums:
      self.set_search_cache(key, albums)     # only a NON-EMPTY result is cached
  if callback:
      callback(albums)
  ```
  ```python
  # services/spotify_service.py:167-170
  except Exception as e:
      self.logger.error(f"Spotify search error: {e}")
      if error_callback:
          error_callback(str(e))             # failure -> no cache entry, no back-off
      return []
  ```
  The single back-off in the whole codebase is the SoundCloud client-id scrape (`services/soundcloud_service.py:181-182, 209`: `_client_id_retry_at = time.monotonic() + 10.0`), and it covers only the client-id discovery, not the search itself.
- **Reproduction / verification:** Point `services/spotify_service.py::_session.get` at a closed port (or monkeypatch `_cached_spotify_search` to raise) and call `SpotifyService.search("q", callback=...)` three times: three `ITunesGateway.get` calls, zero cache entries afterwards. `tests/test_provider_performance.py:82-102` pins exactly this behaviour as *desired* ("transient failure is retried after network recovers") — so the gap is the missing distinction between *transient* and *persistent* failure.
- **Suggested fix:** Add a per-provider failure counter with an open-circuit window (e.g. 3 consecutive failures → skip the provider for 30–60 s) and cache negative results with a short TTL, so a *transient* failure still retries quickly but a *dead* provider is not hammered.
- **Fix side effects:** After the circuit opens, a provider that has just come back stays dark until the window expires; the recovery path must half-open the circuit with a single probe request.
- **Discovered by:** B

---

#### F-WX-05-4  [P2] — The 6-worker search dispatch pool is shared with 8-second catalog lookups, so the provider deadline clock does not start on time

- **File:** `core/api.py:363` (pool), `core/api.py:2264` (album details), `core/api.py:3508` (artist preview); `services/catalog_service.py:169`
- **Confirmed:** yes
- **Description:** `AppApi._search_executor` has 6 workers. Two of its users are *long* network tasks: the album-detail lookup and the artist-candidates preview, each with an 8-second deadline inside `CatalogService`. The per-provider search deadline timer is created **inside** `_run_provider`, i.e. only after a worker picks the task up.
- **Cause:** One pool serves "dispatch a fan-out" (microseconds) and "do a catalogue lookup" (up to 8 s) with no separation.
- **Trigger conditions:** Several album/artist panels are opened (each `get_album_details` call occupies a worker for up to 8 s) at the same time as a search.
- **User impact:** The effective search latency becomes *queue delay + 8 s SoundCloud ceiling*. Worst case measured from the code: 8 s of queueing plus 8 s of provider ceiling = ~16 s before `search_completed` arrives.
- **Evidence:**
  ```python
  # core/api.py:363
  self._search_executor = ThreadPoolExecutor(max_workers=6, thread_name_prefix="SearchWorker")
  # core/api.py:2264  (get_album_details -> catalog lookup, up to 8 s)
  self._search_executor.submit(run)
  # core/api.py:3508  (artist candidates preview, up to 8 s)
  self._search_executor.submit(preview)
  ```
  ```python
  # services/catalog_service.py:168-169
  def album_details(self, album, local_lookup=None, is_current=lambda: True, _deadline=None):
      deadline = _deadline if _deadline is not None else time.monotonic() + 8
  ```
- **Reproduction / verification:** Fill `_search_executor` with 6 tasks that sleep 8 s (the album-detail duration), then call `AppApi.search("q", source="all")` and timestamp the `search_results`/`search_completed` events: the first provider event lands at ≈ +8 s instead of ≈ +0 s.
- **Suggested fix:** Give the catalogue/artist lookups their own pool (`_catalog_pool` already exists with 4 workers in `services/catalog_service.py:14` — route the bridge's album/artist-preview work through it) and leave `_search_executor` for fan-out dispatch only.
- **Fix side effects:** One more pool; `get_album_details`/`get_artist_profile` would need to keep the same event contract.
- **Discovered by:** B

---

#### F-WX-05-5  [P2] — The "Spotify" provider is an Apple/iTunes gateway, mislabelled as Spotify end to end

- **File:** `services/spotify_service.py:31`, `:63`, `:50`; `core/app.py:311-321`; `ui/web_new_v2/index.html:379`; `ui/web_new_v2/js/search.js:178`
- **Confirmed:** yes
- **Description:** The provider the UI calls "Spotify" never contacts Spotify. It queries `itunes.apple.com` and then stamps the results with `source: "spotify"` and a `source_id` that is a **YouTube search expression**. Playback of such a track is resolved through the YouTube service. There is no Spotify Web API call anywhere in `services/` (`grep "api\.spotify\.com"` → 0 hits outside tests/`zapret_service.py`'s domain list).
- **Cause:** The provider was written as a catalogue gateway (Apple's public search API is keyless, Spotify's is not) but kept Spotify's name, so the `source` field — which the rest of the app uses as the *resolution contract* — became a fiction.
- **Trigger conditions:** Every "Spotify" search and every "All platforms" search.
- **User impact:**
  1. **Disclosure:** the user is told their query goes to Spotify; it actually goes to **Apple** and (for the `source_id`) to **Google/YouTube**. The UI says "Поиск в Spotify..." (`search.js:178`) and the dropdown button is titled "Spotify" (`index.html:379`).
  2. **Resolution contract:** a track stored with `source="spotify"` is played by extracting a *YouTube* match (`core/app.py:311-321` routes `source in ("youtube","spotify")` to `self.youtube`). The library therefore contains rows labelled "Spotify" whose audio is a YouTube video, and whose `source_url` points at `itunes.apple.com` (`spotify_service.py:51`).
- **Evidence:**
  ```python
  # services/spotify_service.py:27-31
  def _cached_spotify_search(query: str, limit: int = 20, is_current=None) -> tuple:
      encoded_query = urllib.parse.quote(query)
      results = []
      try:
          url = f"https://itunes.apple.com/search?term={encoded_query}&entity=song&limit={limit}"
  ```
  ```python
  # services/spotify_service.py:42-52
  results.append((
      f"spotify_{item.get('trackId', idx)}",
      title, artist, album, duration, cover_url,
      "spotify",
      f"ytsearch1: {artist} - {title}",        # <- a YouTube query, not a Spotify id
      item.get("trackViewUrl", f"https://open.spotify.com/search/{encoded_query}")
  ))
  ```
  ```python
  # core/app.py:311-321
  if source in ("youtube", "spotify"):
      ...
      service = self.youtube
  ```
- **Reproduction / verification:** `wx05_probe.py`/static read confirm the URL and the `source_id`. Trace one search result with `source="spotify"` into `AppApi.play_track` → `_resolve_track` → `AppCore.re_resolve_stream_url_async` → `service = self.youtube` → the YouTube extractor.
- **Suggested fix:** Either rename the provider to what it is (`itunes`) and update the UI labels, or implement the real Spotify Web API behind the existing `SpotifyService` seam (OAuth is already supported for the Yandex/Spotify OAuth settings, see `core/settings.py:247-248`). At minimum, the platform label must match the destination.
- **Fix side effects:** Renaming `source` is a data-migration issue (existing `tracks.source='spotify'` rows and `stream_cache` rows). A real Spotify implementation needs a user credential and a quota story.
- **Discovered by:** B

---

#### F-WX-05-6  [P2] — An abandoned provider flight keeps its single-flight key occupied forever, so that query can never succeed again

- **File:** `services/base_service.py:140-161`; `core/api.py:2199-2204`
- **Confirmed:** yes
- **Description:** `BaseMusicService._join_request` registers the caller under a key in `self._pending_requests` and only removes it when the provider's `finish()` runs. The bridge's own timeout does **not** release it: `_on_timeout` → `_finish([])` only flips the bridge-local `is_done` flag. The provider's listener therefore stays registered, and any later request for the same key **joins the dead flight** — and its callback is never invoked, so the second request also ends in an empty result.
- **Cause:** Two independent completion mechanisms (provider callback, bridge watchdog) with no shared cancellation path, and no TTL/eviction on `_pending_requests`.
- **Trigger conditions:** The provider is slow enough that the bridge gives up (6 s / 8 s) but the provider's flight is still alive, and the user re-issues the same query in that window. The window is unbounded if the provider never calls back at all (a hung yt-dlp call, a saturated provider pool, a dropped task).
- **User impact:** A query that worked once returns "nothing found" on every repetition for as long as the dead flight is registered — up to the rest of the session. The provider's own result is delivered into a dead flight and silently dropped.
- **Evidence:**
  ```python
  # services/base_service.py:140-161
  def _join_request(self, key, callback, error_callback):
      with self._cache_lock:
          listeners = self._pending_requests.get(key)
          if listeners is not None:
              listeners.append((callback, error_callback))
              return False, None, None        # <- join a flight that may already be dead
          self._pending_requests[key] = [(callback, error_callback)]
      def finish(data=None, error=None):
          with self._cache_lock:
              listeners = self._pending_requests.pop(key, [])   # <- only place the key is freed
  ```
  ```python
  # core/api.py:2199-2204  (the bridge watchdog does not touch _pending_requests)
  def _on_timeout():
      with lock:
          if is_done[0]:
              return
      logger.warning("%s search timed out after %.1fs", name, _timeout)
      _finish([])
  ```
- **Reproduction / verification:** `wx05_probe.py` case 5:
  ```
  leader: True   pending: ['k1']
  second identical request -> leader: False  (callback will never fire)
  pending entries: ['k1']
  ```
  A live variant: drive `AppApi.search` with a provider that answers at 7 s (YouTube, 6 s deadline), then repeat the same query — the second search produces no `search_results` chunk for that provider at all and ends in an empty result.
- **Suggested fix:** Give the bridge watchdog a way to release the flight (`_join_request` should return a cancel handle, and the timeout path should call it), and/or add a TTL to `_pending_requests` entries so an abandoned flight is reclaimed.
- **Fix side effects:** Cancelling a flight must not cancel the provider's underlying work (the provider would still complete and call back into a dead listener) — the provider needs to tolerate a cancelled listener.
- **Discovered by:** B

---

#### F-WX-05-7  [P3] — The Yandex search cache key omits `max_results`, so a small search poisons a larger one

- **File:** `services/yandex_service.py:115` (owner: **WN-21**)
- **Confirmed:** yes (latent — the provider is currently disabled in the UI fan-out)
- **Description:** `cache_key = f"ya_search:{query}"` contains neither the requested result count nor the result type, unlike every other provider.
- **Cause:** The key was written for a single-shape query and never generalised.
- **Trigger conditions:** Two Yandex searches for the same query with different `max_results` (e.g. `5` then `20`).
- **User impact:** The second search returns the first search's (smaller) result list — a silently truncated result set. Currently unreachable from the UI (`DISABLED_UI_PROVIDERS` in `core/api.py:2098` contains `"yandex"`), so the impact is latent, but the service is still constructed and its `search()` is public.
- **Evidence:**
  ```python
  # services/yandex_service.py:113-116
  def _search():
      try:
          cache_key = f"ya_search:{query}"      # <- no max_results, no result_type
          cached = self.get_search_cache(cache_key)
  ```
  Compare:
  ```python
  # services/youtube_service.py:382
  cache_key = f'yt_search:{query}:{yt_filter}:{max_results}'
  # services/soundcloud_service.py:298
  cache_key = f'sc_search:{query}:{max_results}'
  # services/spotify_service.py:111
  key = f'spotify_search:{query}:{result_type}:{limit}'
  ```
- **Reproduction / verification:** `wx05_probe.py` case 4: `ya_search:radiohead` is produced for both `max_results=5` and `max_results=20`.
- **Suggested fix:** `cache_key = f"ya_search:{query}:{max_results}"`, mirroring the other providers.
- **Fix side effects:** Existing cached entries become unreachable (they are simply re-fetched once) — harmless.
- **Discovered by:** B

---

#### F-WX-05-8  [P3] — The user's raw query is written verbatim to the on-disk log and travels in the URL of two of the three third parties

- **File:** `core/api.py:2083`; `main.py:104-117`; `services/spotify_service.py:31`; `services/soundcloud_service.py:321`
- **Confirmed:** yes
- **Description:** Every search logs the raw query at INFO level into `~/.nedotify/logs/app.log` (rotating 2 MB × 3 backups). The same query is also placed in the **query string** of the Apple and SoundCloud requests, so it appears in the access log of any proxy the user configured (`auth.proxy_url`) and of Apple/SoundCloud.
- **Cause:** The bridge logs its arguments for debuggability with no redaction policy, and the keyless catalogue APIs only accept a query-string parameter.
- **Trigger conditions:** Every search.
- **User impact:** The user's music taste is retained in plaintext in a file that users routinely attach to bug reports. The query is also visible to whoever controls the network path (the configured proxy, the ISP, the provider).
- **Evidence:**
  ```python
  # core/api.py:2083
  logger.info(f"api.py -> search called: query='{query}', source='{source}', result_type='{result_type}'")
  ```
  ```python
  # main.py:104-116
  logging.basicConfig(
      level=logging.INFO,
      ...
      RotatingFileHandler(os.path.join(_log_dir, 'app.log'),
                          maxBytes=2_000_000, backupCount=3, encoding='utf-8'),
  )
  ```
  ```python
  # services/soundcloud_service.py:321
  url = f"https://api-v2.soundcloud.com/search/tracks?q={encoded}&client_id={cid}&limit={max_results}"
  ```
- **Reproduction / verification:** Static; `logging.basicConfig(level=logging.INFO)` guarantees the line is written. The URL encoding itself is correct (`urllib.parse.quote`) — there is **no** injection into the provider URLs, only the disclosure.
- **Suggested fix:** Log a hash/length of the query instead of the text at INFO (keep the text at DEBUG), and state in the UI that a query is sent to the selected platforms (the platform picker already implies it; the "Spotify → Apple" substitution of F-WX-05-5 does not).
- **Fix side effects:** Losing the raw query in the log makes provider-side support requests harder to correlate; a truncated/hashed form plus the query length keeps most of the value.
- **Discovered by:** B

---

#### F-WX-05-9  [P3] — The local search chunk over-fetches 28 DB columns per row and ships the user's absolute file paths to the WebView

- **File:** `core/database.py:1393-1403` (owner: **WN-12** for the query; WX-05 owns the payload shape)
- **Confirmed:** yes
- **Description:** `search_tracks` does `SELECT * FROM tracks` and returns whole rows, which `core/api.py:2151` ships to the UI verbatim. The rows carry `file_path` (the absolute path of every local track on disk), `metadata_json`, `loudness_lufs`, `peak_volume`, `sample_rate`, `bitrate`, `file_size` — none of which the search UI reads.
- **Cause:** The bridge has no projection step between the DB row and the `search_results` payload, unlike the provider paths, which each hand-build a small dict.
- **Trigger conditions:** Every search that includes the local library (the default "All platforms" search).
- **User impact:** The local chunk is 6× the size of a provider chunk for the same number of visible rows, and the WebView receives the full local filesystem layout of the user's library. The absolute payload is bounded (see §3), so the cost is modest, but the disclosure is not needed.
- **Evidence:**
  ```python
  # core/database.py:1393-1403
  cursor.execute(
      """
      SELECT * FROM tracks
      WHERE title LIKE ? ESCAPE '\\'
         OR artist LIKE ? ESCAPE '\\'
         OR album LIKE ? ESCAPE '\\'
      ORDER BY play_count DESC
      LIMIT ?
  """,
      (like_query, like_query, like_query, limit),
  )
  return [dict(row) for row in cursor.fetchall()]
  ```
- **Reproduction / verification:** `wx05_probe5.py`, real `DatabaseManager` with 60 tracks:
  ```
  local chunk: 50 rows, json = 29858 bytes (29.2 KiB)
  columns per row: 28
  row keys: ['added_at','album','artist','bitrate','cover_path','cover_url','duration','file_path',
             'file_size','format','genre','id','is_cached','is_downloaded','is_favorite','last_played',
             'loudness_lufs','lufs','metadata_json','peak_volume','play_count','sample_rate','source',
             'source_id','source_url','title','track_number','year']
  provider chunk: 20 tracks, json = 4987 bytes (4.9 KiB)
  worst-case one search response over the bridge: 44819 bytes (43.8 KiB) in 4 separate evaluate_js calls
  ```
- **Suggested fix:** Project the local rows to the same field vocabulary the providers use before emitting them (and drop `file_path` from the search payload — the library view already gets it from the DB when it needs it).
- **Fix side effects:** Any frontend code that currently reads a field only the `SELECT *` provides (e.g. `is_downloaded` for a search result row) would break; the projection must be checked against `createTrackElement` in `ui/web_new_v2/js/utils.js`.
- **Discovered by:** B

---

#### F-WX-05-10  [P3] — The 300-slot search cache is a single class-level LRU shared by every subsystem, so the home feed evicts the user's search results

- **File:** `services/base_service.py:125-134`, `:243-276`; `services/recommendation_service.py:337, 466, 502`
- **Confirmed:** yes
- **Description:** `_search_cache` is a **class attribute** of `BaseMusicService`, so it is one dictionary for YouTube, SoundCloud, Spotify, Yandex, `RecommendationService`, `ArtistService`, `CatalogService` and `ITunesGateway`. The 300-entry LRU cap and the 5-minute TTL are therefore global. The recommendation service writes `recommendation:feed:<sha256>`, `recommendation:candidates:<repr(signature)>` and `recommendation:scrobbles:<user>` into the same slots.
- **Cause:** A per-feature cache was implemented as a class attribute for convenience, and the eviction budget was never split per subsystem.
- **Trigger conditions:** A home-feed refresh (which writes 3 recommendation keys, one of them with a ~900-character `repr(signature)` key) interleaved with user searches. 300 slots fill quickly when the feed is refreshed on every profile change.
- **User impact:** The user's provider search results are evicted by unrelated subsystems, so the same query is re-fetched from the network — the opposite of the cache's purpose. The recommendation keys are also 1–3 orders of magnitude larger than a provider key (measured: 894 characters for a 20-seed signature) and are pure key overhead.
- **Evidence:**
  ```python
  # services/base_service.py:125-134
  _cache_lock = threading.RLock()
  _stream_cache: Dict[str, Any] = {}
  _MAX_CACHE_SIZE = 2000
  _STREAM_CACHE_TTL = 6 * 3600.0
  _search_cache: Dict[str, Dict[str, Any]] = {}
  _SEARCH_CACHE_TTL = 300
  _SEARCH_CACHE_MAX_SIZE = 300
  ```
  ```python
  # services/recommendation_service.py:337
  key = 'recommendation:candidates:' + repr(signature)
  ```
- **Reproduction / verification:** `wx05_probe.py` case 2:
  ```
  YouTubeService._search_cache is BaseMusicService._search_cache -> True
  SpotifyService._search_cache is BaseMusicService._search_cache -> True
  YandexService._search_cache is BaseMusicService._search_cache -> True
  RecommendationService._search_cache is BaseMusicService._search_cache -> True
  ```
  `wx05_probe5.py`: `repr(signature)` length for a 20-seed signature = 894 chars (used verbatim as the cache key).
- **Note:** the *key namespaces do not collide* — `yt_search:`, `sc_search:`, `spotify_search:`, `ya_search:` and `recommendation:` are disjoint, and the stream cache is namespaced too (`youtube:`/`soundcloud:`/`yandex:`, `services/youtube_service.py:101-121`). The defect is **eviction coupling**, not key collision.
- **Suggested fix:** Give each subsystem its own bounded cache (a small per-service `OrderedDict` + TTL helper) instead of one class-level dict, or at least partition the 300 slots per namespace.
- **Fix side effects:** `services/yandex_service.py:93-99` and `services/recommendation_service.py:65-68` clear the cache by key prefix; a per-service cache removes that coupling but requires those two methods to be re-pointed.
- **Discovered by:** B

---

### 3. Clean areas

Checked and found correct (no finding raised):

1. **The fan-out is genuinely parallel, not serial.** Measured with the real `AppApi.search` and three hanging providers: `search_completed` arrives at **+8.04 s** = `max(6, 8, 6)`, not `6+8+6 = 20 s`. Each provider gets its own `threading.Timer` inside its own `_search_executor` task (`core/api.py:2168-2230`).
2. **The class-level `_cache_lock` is NOT held during any network call.** The premise in the brief is refuted by measurement: during the iTunes network call the global lock is acquirable in **0.000 s**, and during the 3.5 s rate-limit wait the worst observed wait over 40 acquisitions was **0.2 ms**. `Condition.wait()` correctly releases the underlying `RLock` (`services/itunes_gateway.py:63`), and the HTTP call is outside the `with cls._condition:` block (`services/itunes_gateway.py:64`). The class lock is a short bookkeeping critical section only (`services/base_service.py:142-151, 194-221, 251-276`).
3. **The shared `_SharedExecutor` is not on the search path.** `BaseMusicService._executor` (`_SharedExecutor(max_workers=8)`) is used by `ArtistService`, `RecommendationService` and `LastFMService` only. All four fan-out providers own private pools: YouTube 10, SoundCloud 10, Spotify 5, Yandex 3. Lyrics has its own 6-worker pool and its own instance lock (`services/lyrics_service.py:87, 183`) and downloads have their own pool (`core/downloader.py:459`). So the shared executor is **not** sized against "7 concurrent providers" — the premise does not apply to this codebase.
4. **The PLAY path does not queue behind the search dispatch pool.** `core/app.py:506` starts the resolution on a dedicated `threading.Thread`; the stream-warmup path has its own 2-worker pool (`core/api.py:369`, `core/api.py:3678`), pinned by `tests/test_playback_startup_performance.py:58` ("Stream warmup must not wait behind search"). (The *provider* pool coupling is F-WX-05-1 — a different thing.)
5. **Cache bounds are all finite and all use LRU + TTL.** `_search_cache` 300 entries / 300 s; `_stream_cache` 2000 entries / 21 600 s; `ITunesGateway._entries` 500 entries / 900 s; `ITunesGateway._flights` is emptied in a `finally`; `_TTLCache` instances are bounded (`services/soundcloud_service.py:141-153`). The LRU implementation is correct: `_cache_recent` drops the key before re-inserting so that insertion order == recency order (`services/base_service.py:223-241`), and a hit does not extend the TTL (`services/base_service.py:255-262`).
6. **Local SQL is properly escaped.** `DatabaseManager._like_pattern` escapes `\`, `%` and `_` and every query declares `ESCAPE '\'` (`core/database.py:1349-1364, 1393-1403, 1422-1437, 1445-1451`). The FTS5 path double-quotes embedded quotes (`core/database.py:1371-1376`). No SQL injection, no wildcard injection.
7. **No provider API key is hardcoded.** Last.fm keys come from `LASTFM_API_KEY` or `auth.lastfm_api_key` (`services/lastfm_service.py:134-150`); the SoundCloud `client_id` is scraped at runtime (`services/soundcloud_service.py:173-210`); Yandex/OAuth secrets are user-supplied and are masked on the way to JS (`core/api.py:240-254`).
8. **Provider failures are isolated and the fan-out always terminates.** Each provider runs in its own task; an exception is caught and turned into an empty chunk (`core/api.py:2226-2228`); `mark_done` is called on every path, so `search_completed` is always emitted (measured in every probe run) — the UI spinner never hangs.
9. **The stale-search guard exists and works.** `is_current()` is checked at the top of `_run_provider` (`core/api.py:2169-2171`), so a queued-but-not-started superseded search never touches the network — pinned by `tests/test_api_search.py:46-74`. Spotify additionally threads `is_current` into the catalogue gateway so a *queued* iTunes request aborts (`core/api.py:2218`, `services/itunes_gateway.py:43, 56`).
10. **The bridge payload is bounded and small.** Worst case one search response = **44 819 bytes** across 4 `evaluate_js` calls (`wx05_probe5.py`); `_emit` serialises inside a `try` so a non-serialisable value cannot silently drop the event (`core/api.py:1131-1139`); `_emit` is never called on the UI thread from the search path (the fan-out runs on `SearchWorker`/provider threads), so contract #1 holds.
11. **The provider URLs are correctly encoded.** `urllib.parse.quote(query)` for both the SoundCloud and the iTunes query string (`services/soundcloud_service.py:320`, `services/spotify_service.py:28`); no injection into the third-party URLs.
12. **The `DISABLED_UI_PROVIDERS` path does not hang.** An empty provider list emits `search_completed` immediately (`core/api.py:2131-2135`) — pinned by `tests/test_api_search.py:15-28`.
13. **Duplicate concurrent identical queries are de-duplicated per provider** (`_join_request`), so a repeated query does not fan out into N parallel provider requests (`tests/test_provider_performance.py:36-47`).

---

### 4. Coverage gaps

1. **No live network measurement.** The brief forbids running the real app; all timings come from static reading plus instrumented local probes with stubbed providers. The provider timeout numbers quoted (YouTube 6 s request timeout, yt-dlp `socket_timeout: 10` / `retries: 1` / `extractor_retries: 1`, iTunes `INTERVAL = 3.5` / `PER_MINUTE = 18` / 8 s deadline) are read from the source, not observed.
2. **The real cost of the WebView2 `evaluate_js` marshalling** (`Control.Invoke` from a worker thread) was not measured; the payload sizes are, the marshalling latency is not.
3. **`services/artist_service.py`, `services/catalog_service.py` and `services/lyrics_lookup.py`** were read only where they touch the shared lock/pool; their internals belong to WN-23 / WN-24 / WN-22.
4. **`services/track_resolver.py` is not on the `AppApi.search` path** in the current code (the fan-out calls the providers directly). The scenario brief lists it as the last hop; I found no call from `AppApi.search` to `TrackResolver`. If a resolver hop is intended, it is missing rather than slow — worth confirming with the WN-18 reviewer.
5. **The SoundCloud client-id scraping path** (which can cost up to 6 s on the first query) was not exercised; its effect on the first-search latency is inferred from the code.
6. **The 20-result cap per provider** was verified from the request parameters (`limit=`/`max_results=20` in the bridge default and in each provider's URL), not from a live provider response; a provider that ignores `limit` would not be caught by that reading.
7. **No concurrency stress test was run** (many parallel searches, many concurrent plays) — the pool-saturation numbers in F-WX-05-1 come from a synthetic 10-worker pool, not from the real provider under load.

---

### 5. Architecture improvements (ARCH)

No proven defect attached to these; they are engineering-level recommendations.

- **ARCH-1 — There is no provider interface or registry; the provider set is hardcoded in six places.** Adding a provider requires: the list in `core/api.py:2100`; the disabled-set in `core/api.py:2098`; the per-provider call signature in `core/api.py:2217-2225`; an attribute of exactly that name on `AppCore` (`core/app.py:129-134, 192-206`) because the bridge resolves the provider with `getattr(self._core, name, None)` (`core/api.py:2213`); the icon map and placeholder in `ui/web_new_v2/js/search.js:45-50, 174-180`; and the dropdown markup in `ui/web_new_v2/index.html:363-379` plus the source filter at `ui/web_new_v2/js/search.js:354`. A `ProviderRegistry` (name → factory → capability descriptor) consumed by both the bridge and the UI would collapse this to one place.

- **ARCH-2 — The provider call protocol is probed at runtime with `except TypeError`.** `core/api.py:2219-2223` calls `srv.search(query, result_type=..., ...)` and, on `TypeError`, retries without `result_type`. This doubles as a bug: a `TypeError` raised *inside* a provider's own code (not a signature mismatch) causes a second, unintended provider request. An explicit `supports_result_type` capability flag, or a uniform `search(query, *, result_type=None, limit=20, callback, error_callback, is_current)` signature, removes both the fragility and the accidental double request.

- **ARCH-3 — Per-provider result normalisation is duplicated four times with three different field vocabularies.** YouTube emits 8 fields (`services/youtube_service.py:490-498`), SoundCloud 9 including `waveform_url` but no `album` (`services/soundcloud_service.py:340-349`), Spotify 10 including `is_favorite` but with a `source_id` that is a YouTube expression (`services/spotify_service.py:149-161`), the local path 28 raw DB columns (`core/database.py:1404`). There is no shared track schema, so a new field must be added in four places and a forgotten one silently becomes `undefined` in the UI. A single `normalize_track(raw, source)` in the bridge (or a `Track` dataclass per provider) would make the drift impossible.

- **ARCH-4 — The provider timeout budget is duplicated in four places and already inconsistent.** `PROVIDER_SEARCH_TIMEOUT = 6.0` (`core/api.py:61`), the 8 s SoundCloud exception (`core/api.py:2197`), the 6 s YouTube request timeout (`services/youtube_service.py:201-205`), the 3.5 s iTunes request timeout and 8 s gateway deadline (`services/spotify_service.py:32`, `services/itunes_gateway.py:26`), plus the yt-dlp `socket_timeout: 10` / `retries: 1` (`services/soundcloud_service.py:272-280`). A single declarative budget per provider (request timeout ≤ bridge deadline ≤ user-visible wait) would have made F-WX-05-2 impossible to write.

- **ARCH-5 — The global `BaseMusicService._cache_lock` is also the iTunes gateway's condition variable.** `services/itunes_gateway.py:15`: `_condition = threading.Condition(BaseMusicService._cache_lock)`. Measured to be harmless for network calls today (worst observed contention 0.2 ms), but it means the global rate limiter's wake-up and every provider's cache bookkeeping contend on one object, and `BaseMusicService._cache_lock` is a *class* attribute that nine subclasses share. A dedicated lock for the gateway, and per-subsystem caches (ARCH-6), would remove the coupling.

- **ARCH-6 — The class-level caches should be per-subsystem instances.** `_search_cache` / `_stream_cache` being class attributes makes the 300/2000 entry budgets global (F-WX-05-10) and forces the prefix-scoped `clear` hacks in `services/yandex_service.py:93-99` and `services/recommendation_service.py:65-68`. A small `TTLCache` helper (the pattern already exists in `services/soundcloud_service.py:17-49`) per service instance would give each subsystem its own budget, TTL and clear semantics, and would remove the need for the `youtube:`/`soundcloud:`/`yandex:` key prefixes as a collision guard.

- **ARCH-7 — The bridge returns a value *and* streams events for one operation.** `AppApi.search` returns `{"query": query, "tracks": []}` (`core/api.py:2232`) and separately emits `search_results` / `search_completed`. The frontend therefore has two completion signals for the same operation, and the return value is always empty. Either the return value should carry the (synchronous) local result, or the return value should be dropped and the event contract made the single source of truth.

- **ARCH-8 — `LastFMService` shadows the class lock with an instance lock of the same name.** `services/lastfm_service.py:116` assigns `self._cache_lock = threading.Lock()` while the inherited class methods use `cls._cache_lock` (the class-level `RLock`). Two different locks with the same name in one class hierarchy is a latent trap: any future `with self._cache_lock:` in a `BaseMusicService` subclass would guard a different object than the one `get_search_cache`/`set_search_cache` use.
