## AREA WN-18 — Service base class, track resolver, music matching, artist identity — ROLE A

### 1. Scope reviewed

**Files opened (path: line ranges actually read):**

- `services/base_service.py` — L1–329 (whole file; `normalize_proxy_url` L25–62, `_PROXY_SCHEMES` L22, `_SharedExecutor` L65–118, `BaseMusicService` L121–329 incl. `_join_request` L140–161, `submit` L163–172, `shutdown_executor` L174–184, `get_from_cache` L186–214, `set_to_cache` L216–221, `_cache_recent` L223–241, `get_search_cache` L243–263, `set_search_cache` L265–270, `clear_search_cache` L272–276, `_parse_yt_entry` L278–313)
- `services/track_resolver.py` — L1–476 (whole file; `_TrackResolverExecutor` L21–72, pool+atexit L75–76, `TRACK_MATCH_MIN_SCORE` L80, `TrackResolver` L83–461, `_memo_key` L117–119, `_memo_get/_memo_put` L121–141, `_unresolved` L143–153, `_search_local` L155–236, `_is_plausible_match` L238–246, `_search_soundcloud` L248–288, `_search_youtube` L290–330, `resolve_track` L332–340, `_resolve_uncached` L342–360, `resolve_tracks` L362–433, `prefetch` L435–441, `resolve_track_async` L443–461, module `resolve_track` L464–468 / `resolve_tracks` L471–476)
- `services/music_matching.py` — L1–95 (whole file; `VERSION_PATTERNS` L8–17, `_PRESENTATION` L18, `normalize` L21–24, `similarity` L27–35, `credits` L38–45, `artist_matches` L48–52, `title_metadata` L55–95)
- `services/artist_identity.py` — L1–63 (whole file; `DEFAULT_ALIASES` L6, `name_key` L9–10, `artist_aliases` L13–32, `binding_key` L35–38, `artist_binding` L41–45, `canonical_artist` L48–54, `track_key` L57–63)

**Callers traced into other areas (read for call-chain attribution only):**

- `core/api.py` — `search` L2077–2232, `_resolve_track` L1608–1744, `_store_artist_binding` L3461–3475, `get_artist_profile` L3477–3513, disliked/blocked filter L2968–2996, alias save L3003–3018
- `core/resolver.py` — L1–271 (whole file; `StreamResolver` single-flight/mem/DB cache)
- `core/app.py` — L545–586 (cleanup: shared-pool shutdown ordering)
- `core/playback_recovery.py` — L1–50 (`same_recording`, the only `similarity` threshold user)
- `core/database.py` — L150–219 (`conn` is a thread-local property; `threading.local()` L155)
- `core/downloader.py` — L500–559 (Spotify download → `TrackResolver` path)
- `services/youtube_service.py` — L180–519 (`__init__` L192–225, `_get_ydl_opts` L293–363, `search` L370–513)
- `services/soundcloud_service.py` — L120–399 (`__init__` L129–171, `_get_ydl` L237–264, `search` L295–399)
- `services/spotify_service.py` — L95–174 (search cache key + own executor)
- `services/itunes_gateway.py` — L1–90 (borrows `BaseMusicService._cache_lock` as a `Condition` lock)
- `services/recommendation_service.py` — L400–509, L615–644 (`resolve_tracks` caller, `_async_recommendation`)
- `services/lyrics_service.py` — L285–324 (`_title_match_score` → `similarity`/`title_metadata`)
- `services/lyrics_lookup.py` — L240–309 (consumer of `title_metadata(...)['artists']`)
- `services/lastfm_service.py` — L92–131 (uses the **class-level** shared executor)
- `services/artist_service.py` — L320–388 (uses the class-level shared executor)
- `tests/test_resolve_fallback_budget.py` — L1–98 (this test targets `core.app._SC_FALLBACK_BUDGET_S`, **not** `services/track_resolver.py`; the resolver has no budget constant of that name)
- `tests/test_track_resolver_matching.py`, `tests/test_cache_lru.py`, `tests/test_proxy_url_validation.py` — executed (73 passed)

**Commands run:** `pytest tests/test_track_resolver_matching.py tests/test_cache_lru.py tests/test_proxy_url_validation.py tests/test_resolve_fallback_budget.py -q` → **73 passed**. Plus five read-only probes (scripts under `%TEMP%\opencode\`, nothing written into the repo).

---

### 2. Findings

#### F-WN-18-1  [P1] — `resolve_tracks` applies ONE deadline to the whole batch: items past the first wave come back "unresolved" while their provider calls keep running and saturate the pool

- **File:** `services/track_resolver.py:362-433` (constants `services/track_resolver.py:91-93`, submit `services/track_resolver.py:394`, wait `services/track_resolver.py:403-408`, timeout branch `services/track_resolver.py:414-420`)
- **Confirmed:** yes
- **Description:** `resolve_tracks()` submits every unique (title, artist) pair to the shared 8-worker pool and then waits **once** with `concurrent.futures.wait(..., timeout=wait_timeout)`. There is no per-item timeout and the not-done futures are never cancelled. A single `resolve_track()` can legitimately take up to ~10 s (5 s SoundCloud wait + 5 s YouTube wait, `services/track_resolver.py:270` and `:312`), so with a batch deadline of `BATCH_TIMEOUT = 10.0` only the first wave of 8 can ever land. Everything after it is returned as `source='unknown'` even though the provider is about to answer — and the orphaned tasks keep occupying the pool.
- **Cause:** the batch deadline is modelled as a wall-clock ceiling for the whole list rather than as a per-item budget; `Future.cancel()` is never attempted on the not-done set.
- **Trigger conditions:** any batch with more than ~8 distinct uncached tracks, or a provider that is slower than the deadline. `RecommendationService._collect_candidates` resolves up to 20 pairs at once (`services/recommendation_service.py:438-439`).
- **User impact:** the home feed fills with unplayable "unknown" entries; and because the abandoned tasks are still running, the 8-worker pool stays busy for minutes afterwards, so a subsequent single-track resolution (e.g. the user pressing play) queues behind them and appears to hang.
- **Evidence:**
  ```python
  # services/track_resolver.py:92-93
  BATCH_TIMEOUT = 10.0
  MAX_CONCURRENCY = 8
  # services/track_resolver.py:394-408
  future = _resolver_pool.submit(self.resolve_track, title, artist)
  ...
  _done, not_done = concurrent.futures.wait(
      list(pending.keys()),
      timeout=wait_timeout,
  )
  # services/track_resolver.py:414-420
  if future in not_done:
      logger.debug(f"Batch resolve timed out for '{artist} - {title}'")
      unresolved = self._unresolved(title, artist)
      self._memo_put(key, unresolved)
  ```
  `MAX_CONCURRENCY` (L93) is declared but **never referenced** anywhere in the file (verified by `Select-String`), so the only bound is the pool size.
- **Reproduction / verification:** probe (`%TEMP%\opencode\wn18_probe4.py`) with a fake SoundCloud that answers after 3 s:
  ```
  items=20 batch_timeout=3.0 elapsed=3.01s unresolved=20 sc_search_calls=8
  -> provider calls actually issued: 8
  ```
  20 items in, 20 items out as `source='unknown'`, while 8 provider searches were already dispatched and 12 more are queued/running.
- **Suggested fix:** give each future a per-item deadline (e.g. `future.result(timeout=per_item)` in a loop, or a per-item deadline derived from the remaining batch budget), cancel the not-done futures, and size the submission window to `MAX_CONCURRENCY` instead of the whole list.
- **Fix side effects:** cancelling a `Future` only prevents *not-yet-started* work; an already-running provider call still runs to completion, so the pool-saturation symptom needs cooperative cancellation or a per-provider deadline as well.
- **Discovered by:** A

---

#### F-WN-18-2  [P2] — The local-library lookup in the resolver is case-sensitive for Cyrillic: SQLite `LOWER()` is ASCII-only, so the user's own downloaded track is not found

- **File:** `services/track_resolver.py:173-180` (SQL) and `services/track_resolver.py:189-218` (artist filter that *would* have been case-insensitive)
- **Confirmed:** yes
- **Description:** `_search_local()` selects candidates with `WHERE LOWER(title) = LOWER(?)`. SQLite's built-in `LOWER()` folds ASCII only; it leaves Cyrillic untouched. For a Russian-language catalogue (the whole UI is Russian) a stored title `Песня про Лето` is therefore **not** found when the request asks for `песня про лето`. The row is never returned, so the artist-similarity filter below (which uses `similarity()` → `casefold()`, i.e. correctly case-insensitive) never gets a chance to run.
- **Cause:** the case folding is delegated to SQLite instead of to Python, where the module already has a Unicode-correct `casefold()`.
- **Trigger conditions:** any Cyrillic (or Greek, Turkish, …) title where the requested casing differs from the stored casing — e.g. the library row was written by one provider and the request comes from another provider or from a user-typed search.
- **User impact:** the resolver's whole "local first" strategy silently fails for Cyrillic titles: the track is resolved against SoundCloud/YouTube instead of the local file. The user gets a remote copy of a track they already downloaded (different quality, extra network traffic, and nothing plays if the network is unavailable) instead of the local file that the local branch exists to return.
- **Evidence:**
  ```python
  # services/track_resolver.py:174-180
  cursor.execute("""
      SELECT id, title, artist, cover_url, cover_path, source, source_id, source_url, duration, file_path
      FROM tracks
      WHERE LOWER(title) = LOWER(?)
  """, (title.strip(),))
  ```
  Contrast with the Python-side filter that *is* case-insensitive:
  ```python
  # services/track_resolver.py:208
  row_artist = (r.get('artist') or '').strip().casefold()
  ```
- **Reproduction / verification:** in-memory SQLite check:
  ```
  INSERT 'Песня про Лето'
  SELECT ... WHERE LOWER(title)=LOWER('Песня про Лето')  -> 1 row
  SELECT ... WHERE LOWER(title)=LOWER('песня про лето')  -> 0 rows
  SELECT LOWER('ПЕСНЯ')                                -> 'ПЕСНЯ'  (unchanged)
  ```
  i.e. `LOWER()` does not fold Cyrillic, so the second query finds nothing.
- **Suggested fix:** fetch candidates without the SQL `LOWER()` (e.g. compare in Python with `casefold()`, or index a normalised `title_key` column) so the Unicode-aware comparison in `similarity()` is the single source of truth.
- **Fix side effects:** dropping the SQL predicate means more rows are scanned per lookup; the `tracks.title` index is only usable with a SQL-side expression, so a normalised indexed column is the safer option.
- **Discovered by:** A

---

#### F-WN-18-3  [P2] — `TrackResolver` builds its provider clients without a lock: N concurrent resolutions create N `SoundCloudService`/`YouTubeService` instances, each with its own 10-thread pool and a client-id scrape

- **File:** `services/track_resolver.py:248-256` (`_search_soundcloud`) and `services/track_resolver.py:290-298` (`_search_youtube`)
- **Confirmed:** yes
- **Description:** `self.sc_service` / `self.yt_service` are lazily created with a classic check-then-act: `if not self.sc_service: self.sc_service = SoundCloudService(settings=self.settings)`. `TrackResolver` instances are shared (`RecommendationService` holds one, `services/recommendation_service.py:56`) and `resolve_tracks()` dispatches all items to a **multi-threaded** pool, so the very first batch makes 8 threads hit this branch simultaneously. `SoundCloudService.__init__` spawns `ThreadPoolExecutor(max_workers=10)` and immediately submits a client-id scrape (`services/soundcloud_service.py:132`, `:169`); `YouTubeService.__init__` likewise builds a 10-worker pool (`services/youtube_service.py:195`).
- **Cause:** no lock protects the lazy-initialisation of the two shared provider attributes, and the class already has a lock (`_memo_lock`, `_db_lock`) that could have been reused.
- **Trigger conditions:** the first `resolve_tracks()` batch on a fresh `TrackResolver` (or after `core/downloader.py:516` builds a new resolver per Spotify download).
- **User impact:** duplicate provider clients, duplicate client-id scrapes (extra requests to soundcloud.com), and up to 8 × 10 = 80 idle worker threads per batch — none of which is ever shut down, because the losing instances are garbage without `shutdown()` and `core/app.py:572-579` only shuts down the pools it can reach through `self._core`.
- **Evidence:**
  ```python
  # services/track_resolver.py:249-252
  if not self.sc_service:
      try:
          from services.soundcloud_service import SoundCloudService
          self.sc_service = SoundCloudService(settings=self.settings)
  ```
  ```python
  # services/soundcloud_service.py:132, 169
  self._executor = ThreadPoolExecutor(max_workers=10)
  ...
  self._executor.submit(self._get_client_id)
  ```
- **Reproduction / verification:** probe (`%TEMP%\opencode\wn18_probe4.py`, PROBE 3) with a stub `SoundCloudService` and 6 concurrent `_search_soundcloud` calls:
  ```
  SoundCloudService instances created for 6 concurrent calls: 6
  -> one instance per racing thread; each owns ThreadPoolExecutor(max_workers=10) + a client_id scrape
  ```
- **Suggested fix:** create the provider clients eagerly in `__init__`, or guard the lazy creation with a dedicated lock (double-checked) so exactly one instance is built.
- **Fix side effects:** eager creation makes `TrackResolver.__init__` heavier (a `SoundCloudService` starts a client-id scrape) — but `core/downloader.py:516` already constructs a resolver per download, so eager creation there would make that leak *worse*; the fix should be paired with reusing one resolver instance.
- **Discovered by:** A

---

#### F-WN-18-4  [P2] — `credits()` splits the word "featuring" on "feat", producing the corrupt credit "uring Other"

- **File:** `services/music_matching.py:44-45`
- **Confirmed:** yes
- **Description:** the separator alternation lists `\bfeat\.?` **before** `\bfeaturing`. Python's `re` alternation is ordered and the split has no trailing requirement, so at the position of "featuring" the first alternative `\bfeat\.?` matches the four characters "feat" and the split succeeds there. The remainder "uring Other" becomes a second credit.
- **Cause:** alternation order plus the absence of a word-boundary/lookahead guard on the shorter alternative.
- **Trigger conditions:** any provider/DB artist string that uses the long form "X featuring Y" (or a bracketed feature whose text contains "featuring"), which flows into `credits(artist)` from `title_metadata()`.
- **User impact:** `title_metadata(title, artist)` returns a bogus artist entry. `services/lyrics_lookup.py:257` builds the lyrics cache key from `tuple(canonical_artist(a, aliases) for a in metadata['artists'])`, so every lookup for such a track is keyed on `'uring other'` and will not match the same track requested with a differently-spelled artist. `artist_matches()` still returns `True` (the good name is still in the set), so the corruption is silent.
- **Evidence:**
  ```python
  # services/music_matching.py:44-45
  return [p.strip() for p in re.split(r'\s*(?:,|&|\bfeat\.?|\bft\.?|\bfeaturing|\bx\b)\s*',
                                    str(value or ''), flags=re.I) if p.strip() and p.strip().casefold() not in placeholders]
  ```
- **Reproduction / verification:**
  ```
  credits('Artist feat. Other')    -> ['Artist', 'Other']          # correct
  credits('Artist featuring Other') -> ['Artist', 'uring Other']   # BUG
  credits('Artist ft. Other')      -> ['Artist', 'Other']          # correct
  ```
  Also: `title_metadata('Song Name feat. Other - Artist', 'RealArtist')` →
  `artists: ['RealArtist', 'Other - Artist']` (see F-WN-18-10).
- **Suggested fix:** order the alternation longest-first (`\bfeaturing|\bfeat\.?|\bft\.?`) or require a trailing word boundary (`\bfeat\.?\b`) so "feat" cannot match the prefix of "featuring".
- **Fix side effects:** `\bfeat\.?\b` also stops "feat" from splitting "feat." correctly? No — `.` is a non-word char, so `\bfeat\b` still matches "feat." before the dot; verify "feat." and "feat" still split.
- **Discovered by:** A

---

#### F-WN-18-5  [P2] — `normalize_proxy_url` accepts `socks5://`, but PySocks is not a declared dependency: `requests` then raises `InvalidSchema` and every requests-based provider dies

- **File:** `services/base_service.py:22` (`_PROXY_SCHEMES`), `services/base_service.py:55-56` (accept branch), `requirements.txt`
- **Confirmed:** yes for the `requests` behaviour; **hypothesis** for the shipped-build exposure
- **Description:** `_PROXY_SCHEMES` explicitly allows `socks4`, `socks4a`, `socks5`, `socks5h`. `requests` can only dial a SOCKS proxy when PySocks is importable; otherwise `requests.adapters` raises `InvalidSchema("Missing dependencies for SOCKS support.")`. `requirements.txt` declares `requests>=2.31.0,<3` but **not** PySocks (no `requests[socks]`). The dev venv happens to contain `PySocks-1.7.1.dist-info`, but that is an undeclared extra.
- **Cause:** the validator checks "is this a syntactically valid proxy URL" but not "can every consumer in the app actually dial it". The failure mode contradicts the function's own docstring, which promises that an unusable value is ignored rather than applied.
- **Trigger conditions:** a user enters `socks5://127.0.0.1:1080` in `auth.proxy_url` on an installation built from `requirements.txt` without PySocks.
- **User impact:** `services/soundcloud_service.py:165` (REST session), `:256`/`:285` (yt-dlp fallback), `services/youtube_service.py:210`/`:236` (ytmusicapi session) and `services/spotify_service.py:107` all install the proxy → every requests-based provider path raises `InvalidSchema` at request time, which surfaces as "search is broken" rather than "your proxy setting is wrong". yt-dlp itself handles SOCKS natively, so the behaviour is *split*: extraction works, metadata search does not.
- **Evidence:**
  ```python
  # services/base_service.py:22
  _PROXY_SCHEMES = frozenset({"http", "https", "socks4", "socks4a", "socks5", "socks5h"})
  ```
  ```python
  # services/soundcloud_service.py:164-167
  if self.settings:
      proxy = normalize_proxy_url(self.settings.get('auth', 'proxy_url', ''))
      if proxy:
          self._session.proxies = {'http': proxy, 'https': proxy}
  ```
  `requirements.txt` contains `requests>=2.31.0,<3` and no PySocks entry.
- **Reproduction / verification:** blocking the `socks` import and issuing a proxied request:
  ```
  InvalidSchema : Missing dependencies for SOCKS support.
  ```
  and `normalize_proxy_url('socks5://127.0.0.1:1080')` → `'socks5://127.0.0.1:1080'` (accepted).
  *Missing evidence for the shipped-build half:* I did not inspect the installer/build scripts (`WN-01` owns `setup_pyinstaller.spec` / `installer.iss`); a grep of `installer.iss` for `requirements|pip install|python` returned nothing, so how the packaged app obtains its dependencies is unverified.
- **Suggested fix:** either declare PySocks in `requirements.txt` (and in the PyInstaller hidden-imports), or restrict `_PROXY_SCHEMES` to the schemes the requests stack can actually use and route SOCKS only through the yt-dlp path.
- **Fix side effects:** adding PySocks grows the wheel; removing `socks*` from `_PROXY_SCHEMES` would break users who legitimately use a SOCKS proxy with yt-dlp only.
- **Discovered by:** A

---

#### F-WN-18-6  [P3] — `similarity()` is order-dependent: `difflib.SequenceMatcher.ratio()` is not symmetric

- **File:** `services/music_matching.py:27-35`
- **Confirmed:** yes (the asymmetry); **no** user-visible threshold flip demonstrated
- **Description:** `similarity(want, got)` returns `SequenceMatcher(None, a, b, autojunk=False).ratio()`. `difflib`'s matching-block algorithm is not symmetric: the number of matched characters can differ depending on which string is `a`. The function therefore returns different values for `similarity(x, y)` and `similarity(y, x)`.
- **Cause:** `difflib.SequenceMatcher` is a heuristic, not a metric.
- **Trigger conditions:** any pair of strings with partial overlap; the two thresholds in the codebase are `TRACK_MATCH_MIN_SCORE = 0.6` (`services/track_resolver.py:80`) and `0.88` (`core/playback_recovery.py:22`).
- **User impact:** latent — the same pair can be accepted in one call direction and rejected in the other, so "is this the same recording?" can depend on which side the caller happened to pass first. I could **not** produce a realistic music-title pair that crosses either threshold (see reproduction), so I rate this P3 rather than higher.
- **Evidence:**
  ```python
  # services/music_matching.py:33-35
  if min(len(a.replace(' ', '')), len(b.replace(' ', ''))) <= 4:
      return 0.0
  return SequenceMatcher(None, a, b, autojunk=False).ratio()
  ```
- **Reproduction / verification:** random search over short strings (`%TEMP%\opencode\wn18_probe2.py`):
  ```
  'ceaaedbcbd' vs 'aaeeccced': fwd=0.421053 rev=0.526316 delta=0.105263
  'daacdaacedcd' vs 'adcbeada': fwd=0.200000 rev=0.400000 delta=0.200000
  'aae' vs 'eacea': fwd=0.500000 rev=0.250000 delta=0.250000
  ```
  A realistic-title sweep (22 hand-picked track titles, all permutations, `%TEMP%\opencode\wn18_probe5.py`) produced **0** threshold flips at 0.6 or 0.88, and a 20 000-sample word-salad sweep produced **0** flips at 0.88 — hence P3.
- **Suggested fix:** make the comparison explicitly symmetric, e.g. `max(ratio(a, b), ratio(b, a))`, or replace `difflib` with a symmetric metric (token-set / Jaccard over normalised tokens).
- **Fix side effects:** `max()` of the two directions would loosen matching slightly — the 0.88 recovery gate would accept a few more candidates; re-check `tests/test_playback_recovery.py` expectations.
- **Discovered by:** A

---

#### F-WN-18-7  [P3] — `normalize_proxy_url` accepts any host, including loopback and link-local/metadata addresses

- **File:** `services/base_service.py:44-56`
- **Confirmed:** yes
- **Description:** the validator only requires a known scheme and a non-empty hostname. `http://127.0.0.1:1080` is the documented use case, but so are `http://169.254.169.254/latest/meta-data`, `http://metadata.google.internal`, `http://[::1]:8080` and any RFC1918 address. The proxy value is then installed into `requests` sessions and yt-dlp options for **every** provider call.
- **Cause:** no destination validation is applied to the proxy target, unlike the URL-import path in `core/api.py`, which does apply `_is_ssrf_safe_url`.
- **Trigger conditions:** a user (or anything that can write `auth.proxy_url` through the settings API) sets a link-local/metadata host.
- **User impact:** all provider traffic is redirected to an arbitrary local endpoint. Impact is limited (it is a local setting, and the request is a proxy CONNECT rather than a plain GET), but the failure is global and silent — every provider stops working at once.
- **Evidence:**
  ```python
  # services/base_service.py:55-56
  if scheme in _PROXY_SCHEMES and hostname:
      return value
  ```
  Measured: `normalize_proxy_url('http://169.254.169.254/latest/meta-data')` → returned unchanged; `'http://127.0.0.1:1080'` → returned unchanged; `'ftp://127.0.0.1:21'` and `'file:///C:/Windows/win.ini'` → correctly rejected (`""`).
- **Reproduction / verification:** the `normalize_proxy_url` table in `%TEMP%\opencode\wn18_probe3.py`.
- **Suggested fix:** log the resolved proxy target at INFO/WARNING once per change, and optionally reject link-local/metadata hostnames (keeping loopback, which is the documented case).
- **Fix side effects:** rejecting loopback would break the documented use case; reject only the link-local/metadata ranges, and keep `127.0.0.1`.
- **Discovered by:** A

---

#### F-WN-18-8  [P3] — The class-level `_search_cache` is shared by every provider **and** the recommendation feed, and `clear_search_cache()` has no callers, so a settings/account change leaves stale results for 5 minutes

- **File:** `services/base_service.py:132-134`, `services/base_service.py:243-276`, `services/base_service.py:272-276`
- **Confirmed:** yes
- **Description:** `BaseMusicService._search_cache` is a **class** attribute, so every subclass and every instance shares one 300-entry LRU with a 300 s TTL. The provider caches are protected from key collisions only by their prefixes (`yt_search:` `services/youtube_service.py:382`, `sc_search:` `services/soundcloud_service.py:298`, `spotify_search:` `services/spotify_service.py:111`), but `RecommendationService._feed_tracks` stores whole feed lists under `recommendation:feed:<sha>` in the **same** dict (`services/recommendation_service.py:467`, `:478`). `clear_search_cache()` — the only way to invalidate it — has **zero callers** in the repository (grep over `*.py` returns only the definition).
- **Cause:** a class-level cache with no invalidation hook wired to the settings/auth lifecycle.
- **Trigger conditions:** the user changes `auth.proxy_url`, the YouTube cookie file, or signs into a different account → the old results stay served for up to 5 minutes; and a burst of feed regenerations can evict live provider search entries from the shared 300-entry LRU.
- **User impact:** stale search results after an account/proxy change (the app appears to ignore the new proxy for up to 5 minutes), and cross-cache eviction between the home feed and provider searches.
- **Evidence:**
  ```python
  # services/base_service.py:132-134
  _search_cache: Dict[str, Dict[str, Any]] = {}
  _SEARCH_CACHE_TTL = 300
  _SEARCH_CACHE_MAX_SIZE = 300
  ```
  ```python
  # services/base_service.py:272-276
  @classmethod
  def clear_search_cache(cls) -> None:
      """Clear all search cache entries."""
      with cls._cache_lock:
          cls._search_cache.clear()
  ```
- **Reproduction / verification:** `Select-String -Path <repo> -Pattern "clear_search_cache"` → 2 hits, both inside `services/base_service.py` (definition + body). No caller anywhere.
- **Suggested fix:** call `clear_search_cache()` when `auth.proxy_url` / cookie / account settings change, and give the recommendation feed its own cache namespace or instance-level dict so it does not share the provider LRU.
- **Fix side effects:** clearing on every settings write would defeat the cache during unrelated settings churn; scope it to the auth/proxy keys.
- **Discovered by:** A

---

#### F-WN-18-9  [P3] — A pending-request entry leaks when the provider's `submit()` raises: that search key is permanently dead on the instance

- **File:** `services/base_service.py:140-161` (`_join_request`), `services/youtube_service.py:388-512`, `services/soundcloud_service.py:304-402`
- **Confirmed:** yes
- **Description:** `_join_request()` registers the listener under `self._pending_requests[key]` and returns "leader". The leader then submits the actual work; `YouTubeService.search` does `self._executor.submit(_search)` (`services/youtube_service.py:512`) and `SoundCloudService.search` does `self._executor.submit(_search)` (`services/soundcloud_service.py:402`), neither inside a `try`. `ThreadPoolExecutor.submit` raises `RuntimeError('cannot schedule new futures after interpreter shutdown')` once the pool is shut down. The exception escapes `search()` **before** any callback runs, so the `_pending_requests[key]` entry is never popped.
- **Cause:** the pending entry is removed only by `finish()` (`services/base_service.py:149-151`), which is only reached through a success/error callback. A failure *before* the task starts leaves the key permanently marked "in flight".
- **Trigger conditions:** any `search()` call issued after the provider's pool was shut down (`core/app.py:572-579` shuts the pools during cleanup; `BaseMusicService.shutdown_executor()` shuts the shared pool).
- **User impact:** for that key, every later request on that instance returns immediately with **no callback** (`_join_request` returns `(False, None, None)` and the caller does `if not leader: return None`), so the caller waits for its own timeout. The pending map also grows without bound for the life of the instance.
- **Evidence:**
  ```python
  # services/base_service.py:142-147
  with self._cache_lock:
      listeners = self._pending_requests.get(key)
      if listeners is not None:
          listeners.append((callback, error_callback))
          return False, None, None
      self._pending_requests[key] = [(callback, error_callback)]
  ```
  ```python
  # services/youtube_service.py:512
  self._executor.submit(_search)
  ```
- **Reproduction / verification:** observed in the probe run — the YouTube fallback path logged `YouTube track resolution error: cannot schedule new futures after interpreter shutdown` (the exception is caught by `_search_youtube`'s `except Exception` at `services/track_resolver.py:327-329`, but the *pending entry* for the search key is never cleaned).
- **Suggested fix:** wrap the `submit()` calls in `try/except RuntimeError` and, on failure, invoke the error callback (which pops the pending entry) — or make `_join_request` return a cleanup handle the caller must call.
- **Fix side effects:** calling the error callback on a submit failure changes the provider's error path from "exception propagates to the bridge" to "error callback"; the bridge already handles both.
- **Discovered by:** A

---

#### F-WN-18-10  [P3] — `title_metadata` loses the artist in the "Song feat. X - Artist" form and keeps "(Remastered 2011)" in `base_title`, so the dislike/block filter and the 0.88 recovery gate miss variants

- **File:** `services/music_matching.py:64-95`, `services/artist_identity.py:57-63`
- **Confirmed:** yes
- **Description:** two related gaps:
  1. For the reverse-credit form `Song feat. X - Artist`, `trailing_feature` (L64-67) captures `"X - Artist"` as one blob, `credits()` does not split on `" - "`, and `clean` becomes `"Song"` — so the `" - "` split at L71 never fires, `embedded` stays `None`, and `reverse_credit` (L95) is `None`. The real artist name is lost; the artists list becomes `['<passed artist>', 'X - Artist']`.
  2. `VERSION_PATTERNS` (L8-16) has no `remaster` entry, so `"Song (Remastered 2011)"` keeps its qualifier in both `title` and `base_title` (L93). `track_key` (`services/artist_identity.py:58-59`) likewise only strips `(official video)`, `(lyrics)`, `(visualiser)`.
- **Cause:** the reverse-credit detection is gated on `embedded`, but `embedded` can only be set when `clean` still contains a `" - "` separator — which the trailing-feature truncation removes in the forward-credit form.
- **Trigger conditions:** metadata in the form `"<title> feat. <guest> - <artist>"` (common in YouTube Music titles), and any "(Remastered …)" title.
- **User impact:** the disliked/blocked-track filter (`core/api.py:2968-2996`, keyed on `track_key`) does not match a remastered or feature-variant of a blocked track, and `same_recording` (`core/playback_recovery.py:22`) rejects a remastered candidate: `similarity("Song", "Song (Remastered 2011)") = 0.68` against a 0.88 gate, so stream renewal treats the same song as a different recording.
- **Evidence:**
  ```python
  # services/music_matching.py:64-67
  trailing_feature = re.search(r'\s+(?:feat\.?|ft\.?|featuring)\s+(.+)$', clean, re.I)
  if trailing_feature:
      features.extend(credits(trailing_feature.group(1)))
      clean = clean[:trailing_feature.start()]
  ...
  # services/music_matching.py:95
  'reverse_credit': (parts[1].strip(), parts[0].strip()) if trailing_feature and embedded else None
  ```
- **Reproduction / verification:**
  ```
  title_metadata('Song Name feat. Other - Artist', 'RealArtist')
    -> {'title': 'Song Name', 'base_title': 'Song Name',
        'artists': ['RealArtist', 'Other - Artist'], 'embedded': None, 'reverse_credit': None}

  title_metadata('Song Name (Remastered 2011)', 'Artist')
    -> {'title': 'Song Name (Remastered 2011)',
        'base_title': 'Song Name (Remastered 2011)', 'version': ''}
  ```
  and `similarity('Song Name', 'Song Name (Remastered 2011)') = 0.68` (< the 0.88 gate in `core/playback_recovery.py:22`).
- **Suggested fix:** split the trailing-feature capture on `" - "` before it is credited, and add a `remaster` qualifier to `VERSION_PATTERNS` / to the `track_key` title strip.
- **Fix side effects:** adding `remaster` to `VERSION_PATTERNS` changes `version` from `''` to `'remaster'`, which feeds the `requested["version"] != candidate["version"]` equality check in `core/playback_recovery.py:24` — a remastered candidate would then match a non-remastered request only if both sides agree, which is the intended tightening but changes recovery behaviour.
- **Discovered by:** A

---

### 3. Clean areas

- **`_cache_lock` discipline in `BaseMusicService` is correct.** It is an `RLock` (`services/base_service.py:125`), it is a *class* attribute so every subclass shares one lock, and it is held only for dict operations — never across a network call. `_join_request.finish()` pops the listener list under the lock and invokes the callbacks **outside** it (`services/base_service.py:149-158`), so a slow provider callback cannot block the cache. The `RLock` type is also load-bearing: `services/itunes_gateway.py:15` builds `threading.Condition(BaseMusicService._cache_lock)` and calls `Condition.wait()` (`services/itunes_gateway.py:63`), which needs the RLock's `_release_save()`; a plain `Lock` would raise `AttributeError` there. `Condition.wait()` fully releases an RLock, so there is no deadlock.
- **Both caches are bounded and correctly LRU-evicted.** `_stream_cache` caps at 2000, `_search_cache` at 300 (`services/base_service.py:127-134`). `_cache_recent` (L223-241) drops the key before re-inserting so that dict insertion order really is LRU order, and evicts the oldest entry at the cap. The `get_*` paths re-insert the entry with its **original** timestamp, so a cache hit does not extend the TTL — the comment at L205-207 and the implementation agree.
- **TTL handling is correct.** `_stream_cache` entries expire after 6 h and are additionally rejected when `stream_url_expired(url)` reports an explicit CDN expiry token (`services/base_service.py:201-202`); `_search_cache` entries expire after 300 s (L256-258). The "raw value placed directly into the cache" compatibility branch (L211-214, L263) is consistent between the two getters.
- **Cache keys are complete for the provider searches.** YouTube's key includes query, result-type filter **and** `max_results` (`services/youtube_service.py:382`); SoundCloud's includes query and `max_results` (`services/soundcloud_service.py:298`); Spotify's includes query, `result_type` and `limit` (`services/spotify_service.py:111`). The resolver's own `max_results=1` lookups therefore cannot collide with the UI's `max_results=20` lookups. The stream cache keys are namespaced by provider (`soundcloud:<url>`, `_yt_cache_key(surl)`).
- **`_SharedExecutor` is sound.** It is lazily created behind a lock (no threads at import time), `submit()` returns `None` instead of raising after shutdown or during interpreter finalisation (`services/base_service.py:84-87`), it catches the `RuntimeError` from `pool.submit` and marks itself shut down (L101-106), and `shutdown()` is idempotent and never blocks (`wait=False`, `cancel_futures=True`). `ThreadPoolExecutor` captures a task's exception in the `Future` and does **not** kill the worker thread, so one failing task cannot take down a worker. `core/app.py:563-571` shuts the shared pool down during cleanup, and `services/track_resolver.py:76` registers the resolver pool with `atexit`.
- **No lock is held across a network call in the base service.** `submit()` only touches `pool.submit`, which is non-blocking.
- **`normalize_proxy_url` rejects genuinely malformed values.** A bare token (`"127.0.0.1:1080"`), `"not a url"`, `"http://"` (no host), `"ftp://…"` and `"file:///…"` are all rejected with a warning and fall back to direct egress, exactly as the docstring promises. `socks5h://user:pass@host:1080` and `http://user:pass@host:8080` are accepted (credentials in the URL are supported by both `requests` and yt-dlp).
- **`TrackResolver`'s fallback chain itself is correct.** `_resolve_uncached` tries local → SoundCloud → YouTube and returns `_unresolved()` only when all three fail; each provider step is individually wrapped in `try/except Exception` so a failing provider falls through to the next (`services/track_resolver.py:348-360`, `:285-287`, `:327-329`). The memo key is `title.strip().lower() + '\0' + artist.strip().lower()` (L117-119) — title **and** artist, so different artists do not collide; duration is deliberately not part of the key.
- **The "not found" verdict is short-lived.** `_memo_put` picks `MEMO_TTL = 300` only for `source in ('soundcloud','youtube','local')` and `MISS_TTL = 15` otherwise (`services/track_resolver.py:136`), so a genuine miss is cached for 15 s, not for the full success TTL. The negative-caching blackhole risk is therefore limited to 15 s — except on the batch-timeout path (F-WN-18-1), which writes a miss into the memo for items that never actually failed.
- **A failed item does not abort the batch.** `future.result()` is wrapped in `try/except Exception` and the loop continues (`services/track_resolver.py:422-431`); the final list comprehension back-fills any `None` slot with `_unresolved()`.
- **`_search_local` is thread-safe against the real database.** `core/database.py:155` stores the connection in a `threading.local()`, and `conn` is a property returning the per-thread connection (`core/database.py:203-205`). `TrackResolver._search_local` therefore takes the `has_local_conn_prop` branch and correctly uses the per-thread connection; the `_db_lock` fallback is only for raw non-thread-local connections.
- **`canonical_artist` is case-insensitive, alias-chain-safe and loop-safe.** `name_key` applies NFKC + `casefold()` + `ё`→`е` (`services/artist_identity.py:9-10`), so `"Фараон"` and `"PHARAOH"` collapse through `DEFAULT_ALIASES` to the same key; the `visited` set (`services/artist_identity.py:51-53`) makes a cyclic alias table terminate.
- **`artist_aliases()` reads the right settings slots and degrades safely.** It reads `personalization.artist_aliases` and `personalization.artist_bindings` (`services/artist_identity.py:15`, `:19`), which exist in `core/settings.py:171-172`; non-dict values are ignored (`if isinstance(configured, dict)`). The `SettingsManager.get(category, key, default)` 3-argument signature matches (`core/settings.py:351`).
- **`artist_matches()` cannot produce a name-similarity false positive.** It is an exact set intersection of *canonicalised* names (`services/music_matching.py:50-52`), not a fuzzy score — `"The Beatles"` vs `"Beatles"` → `False`, `"Artist"` vs `"Other"` → `False`. The only false-positive source is an explicit user alias, which is intentional.
- **`similarity()` handles the documented edge cases.** Empty string → `0.0`; `"Live"` vs `"Lies"` → `0.0` (the ≤4-char guard); Cyrillic, `ё`, case and punctuation are all folded by `normalize` (`services/music_matching.py:21-24`); `"AC/DC"` vs `"AC DC"` → `1.0`; a bracketed `(feat. X)` is removed from `base_title` by `title_metadata` before the comparison.

---

### 4. Coverage gaps

- **I did not exercise any provider over the network.** Every provider observation in this report comes from reading the source or from stubbed probes; the `network` marker is deselected in `pytest.ini`.
- **`tests/test_resolve_fallback_budget.py` does not test `services/track_resolver.py` at all.** It imports `_SC_FALLBACK_BUDGET_S` from `core.app` (`tests/test_resolve_fallback_budget.py:11`) and its "cascade" assertions re-implement the guard inline rather than calling shipped code. **The resolver in this area has no budget constant, no test, and no coverage of its batch-timeout semantics** — the timeout behaviour of F-WN-18-1 is untested. (`core.app` / `core/api.py` own that constant; WN-03/WN-05 territory.)
- **I did not verify how the shipped installer obtains its Python dependencies.** `installer.iss` contains no `requirements`/`pip install` reference; the PyInstaller spec was not opened (WN-01 owns it). F-WN-18-5's "fresh install lacks PySocks" half therefore remains a hypothesis.
- **`services/itunes_gateway.py` borrows `BaseMusicService._cache_lock` as a `Condition` lock.** I verified there is no deadlock (the network call is outside the `with` block, `services/itunes_gateway.py:64`) and that `Condition.wait()` releases an RLock fully, but I did not measure the contention this cross-class coupling creates; that is a Role B (architecture) question.
- **I did not measure the real cost of F-WN-18-3's duplicate provider clients** (threads, sockets, client-id requests). The probe counted instances, not resource usage.
- **`core/resolver.py` (`StreamResolver`) was read but produced no findings**: its `_mem`/`_inflight`/`_failed` are all guarded by one `self._lock`, the single-flight re-check under the lock is correct, `_FAIL_TTL = 120.0` is short enough to avoid a permanent "not found" verdict, and `invalidate()` deliberately preserves the unavailable verdict. Its own `resolve_timeout = 12.0` is a wait bound on the flight, not a cancellation of the owner's work — the same "orphan keeps running" pattern as F-WN-18-1, but it is WN-15's area and I did not file it here.
- **No UI-side verification.** I did not load `ui/web_new_v2/js/*` to confirm how an `source='unknown'` result is rendered in the search list or the home feed; the "unplayable entry" impact stated in F-WN-18-1 is inferred from the Python-side shapes only.
- **`music_matching` / `artist_identity` were traced to `services/catalog_service.py`, `services/artist_service.py`, `services/taste_profile.py`, `services/lyrics_lookup.py`, `services/lyrics_service.py` and `core/playback_recovery.py`, but those files were not reviewed** — they belong to WN-15/22/23/24. Where their use of this area's API is defective, the defect is attributed to them.
