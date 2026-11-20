## AREA WN-15 — Stream resolution & playback recovery — ROLE B

### 1. Scope reviewed

**Files opened (full read unless noted):**

- `core/resolver.py` (271 L — full)
- `core/playback_recovery.py` (183 L — full)
- `core/offline.py` (77 L — full)
- `utils/stream_urls.py` (26 L — full)

**Callers / callees traced into other areas (read for context, not audited here):**

- `core/api.py` — `play_track` (L1437), `_resolve_track` (L1608), `recover_stream` (L4166), `prefetch_track` (L3640), `_on_track_changed` (L1195), `set_offline_mode` (L4132), `_offline_bridge_result` (L461), `_install_bridge_error_logging` (L401), `save_setting` (L2940), `get_queue`/`get_next_track` payload builders (L2035).
- `audio/engine.py` — `resolve_stream_url` (L121), `_resolve_via_network` (L153), `_notify_track_changed` (L78).
- `core/app.py` — `AppCore.resolver` construction (L122), `re_resolve_stream_url_async` (L296), cache-cleanup loop (L176).
- `core/proxy.py` — `do_GET` `/api/stream` branch (L795) and `/?url=` branch (L863), `log_message` (L488), `_host_allows_credentials` (L91), `get_proxy_url` (L1304), 403/410 self-heal (L1022).
- `core/database.py` — `stream_cache` schema (L311), `get_cached_stream` (L2149), `cache_stream` (L2162), `invalidate_cached_stream` (L2213), `cleanup_expired_cache` (L2227), thread-local `conn` (L179/L203).
- `services/base_service.py` — `_cache_lock` (L125), `_stream_cache` (L126), `_MAX_CACHE_SIZE` (L127), `_STREAM_CACHE_TTL` (L131), `get_from_cache`/`set_to_cache` (L187/L217).
- `services/soundcloud_service.py` — `_mark_unavailable` (L526), `_unavailable_cache` (L148), `_unavailable_key` (L112), `get_stream_url` (L569), `_media_url_is_servable` (L541).
- `services/music_matching.py` — `normalize`/`similarity`/`artist_matches`/`title_metadata` (L21–95).
- `core/settings.py` — `get`/`set` string→bool coercion (L351/L401).
- `ui/web_new_v2/js/player.js` — `handleStreamError` retry ladder (L448), `playTrack` source selection (L1665–1709).
- `main.py` — `logging.basicConfig(level=logging.INFO)` (L104).

**Probe harness (read-only, written outside the repo):** `C:\Users\Артур\AppData\Local\Temp\opencode\wn15_probe.py`, run with `& ".venv_win\Scripts\python.exe"`. It exercised the single-flight waiter timeout, the re-entrant `resolve()` case, the `mark_unavailable` call-graph, the offline-predicate divergence, the cache bounds and `stream_url_expired`. No repo file was modified.

---

### 2. Findings

#### F-WN-15-1  [P1] — Single-flight waiters time out at 12 s while the owner may still be resolving for ~30 s → a concurrent caller is told "no stream" for a track that does resolve

- **File:** `core/resolver.py:22`, `core/resolver.py:224`; owner budget in `audio/engine.py:208`, `audio/engine.py:278`, `audio/engine.py:447`, `audio/engine.py:482`; consumer at `core/proxy.py:817`, `core/proxy.py:820-825`
- **Confirmed:** yes
- **Description:** `StreamResolver.resolve()` lets exactly one caller own the resolution and makes every other caller for the same key wait on `flight.event` for `_RESOLVE_TIMEOUT = 12.0` seconds. If the wait expires, the waiter returns `None` — it never re-checks the cache and never learns that the owner succeeded a second later. The owner's actual work (`AudioEngine._resolve_via_network`) is bounded by a **20 s cascade budget plus a 10 s direct attempt** (≈30 s worst case), i.e. 2.5× the waiter's patience. Every waiter inside that window gets a false negative.
- **Cause:** two independent budgets were chosen in two files and never reconciled. `core/resolver.py` sizes its waiter timeout for "one provider call" while `audio/engine.py` sizes the cascade for "direct attempt + 3 SoundCloud searches + 3 stream extractions + a YouTube search".
- **Trigger conditions:** two concurrent resolutions of the same `(source, source_id)`. Reachable in production: the proxy's `do_GET` thread calls `engine.resolve_stream_url()` (`core/proxy.py:817` / `:899` / `:925`) while `AppApi.prefetch_track` (`core/api.py:3661`) resolves the same track, or when the `<audio>` element issues a second request (Range/seek/retry) while the first is still in flight.
- **User impact:** the proxy answers `404 Stream not found` (`core/proxy.py:820-825`) for a track that resolves moments later and is then cached correctly — the user hears "не удалось найти поток" for a playable track, and the next attempt works. Recovery is "try again", not a permanent failure, which makes it look like flakiness.
- **Evidence:**
  ```python
  # core/resolver.py:22
  _RESOLVE_TIMEOUT = 12.0  # max wait for a single-flight resolution
  ...
  # core/resolver.py:224
          flight.event.wait(timeout=self._resolve_timeout)
  ```
  ```python
  # audio/engine.py:278  (cascade budget for the SoundCloud tier)
              cascade_deadline = time.monotonic() + 20.0
  # audio/engine.py:447  (SoundCloud direct attempt)
              event.wait(timeout=15)
  # audio/engine.py:482  (YouTube fallback search)
              event2.wait(timeout=10)
  ```
- **Reproduction / verification:** probe §1 — the second `resolve()` on the same key returned `None` after exactly `12.0 s` while the owner was still running (`inflight entries while owner still running: 1`), and the owner then returned `'http://slow/url'` at 12.3 s. Deterministic, no network needed.
- **Suggested fix:** make the waiter timeout ≥ the owner's worst-case budget, and/or — better — have a timed-out waiter re-read the cache once before giving up (`self.get_cached_url(source, source_id)`) instead of returning `None` unconditionally.
- **Fix side effects:** a longer waiter timeout keeps a proxy request thread alive for up to ~30 s; `http.server` is thread-per-request, so a stalled stream pins a thread. The cache re-check adds one indexed SQLite seek per timeout, only on the slow path.
- **Discovered by:** B

#### F-WN-15-2  [P2] — The resolver's negative cache is dead code: `mark_unavailable()` has no production caller, so the "known dead track" gate in `resolve()` can never fire

- **File:** `core/resolver.py:79-122`, `core/resolver.py:181-185`; the only production consumer of the API is `core/playback_recovery.py:85` (which only *clears*); the provider that holds the knowledge is `services/soundcloud_service.py:526-539`
- **Confirmed:** yes
- **Description:** `StreamResolver` ships a negative cache (`_failed`, `_mark_failed`, `is_unavailable`, `mark_unavailable`, `clear_unavailable`) and `resolve()` consults it before running the cascade. Nothing in production ever *writes* it. The one provider that can distinguish "this track is gone" from "the network hiccupped" — SoundCloud, which detects DRM (`soundcloud_service.py:689`), CDN denial (`:615`, `:698`) and yt-dlp "unplayable" errors (`:738`) — records its verdict in its **own** `_unavailable_cache` under a **different key space** (`sc_unavailable:<id>`, `soundcloud_service.py:112-123`) and never notifies the resolver.
- **Cause:** two independent "unavailable" mechanisms were built (resolver-level keyed by `source:source_id`, provider-level keyed by `sc_unavailable:<id>`) and the provider was never wired to the resolver one.
- **Trigger conditions:** always — for every unresolvable track, on every request.
- **User impact:** (a) `resolve()` re-walks the full cascade for a track already known to be dead, so a dead track costs a provider round trip (and, on the SoundCloud branch, a 15 s wait at `audio/engine.py:447`) on every attempt instead of being skipped in microseconds; (b) `is_unavailable()` is always `False`, so any caller that wants to auto-skip a dead track (advance the queue, grey out the row) gets no signal; (c) `clear_unavailable()` at `core/playback_recovery.py:85` is a guaranteed no-op. **Blast radius of the opposite failure** (a false "unavailable" verdict) is bounded and *not* provider-wide: the effective memo is `SoundCloudService._unavailable_cache`, capped at `max_entries=200` with a `3600 s` TTL (`soundcloud_service.py:83`, `:148`), and the two transient-error paths are already guarded (`_media_url_is_servable` returns `True` on 5xx/transport errors — `soundcloud_service.py:550-567`; the yt-dlp path re-raises unless `_is_unplayable_error(exc)` — `soundcloud_service.py:732-738`). Worst case is therefore ≤200 SoundCloud tracks blackholed for 1 h — *not* the whole provider.
- **Evidence:**
  ```python
  # core/resolver.py:181-185  (the gate that can never fire)
          if self._is_failed(key):
              logger.info(
                  f"Skipping resolution of {source}:{source_id}: already known unavailable"
              )
              return None
  ```
  ```python
  # services/soundcloud_service.py:534-539  (the verdict goes somewhere else)
          self.logger.info(f'SoundCloud {track_url} cannot be extracted: {reason}')
          self._unavailable_cache.set(_unavailable_key(track_url), reason)
          with self._cache_lock:
              self._stream_cache.pop(f'soundcloud:{track_url}', None)
  ```
- **Reproduction / verification:** `git grep -n mark_unavailable -- '*.py'` returns only the definitions in `core/resolver.py`, the *unrelated* `SoundCloudService._mark_unavailable` in `services/soundcloud_service.py`, and `tests/test_soundcloud_drm_unavailable.py`. `StreamResolver.mark_unavailable` is never called outside tests; `is_unavailable()` therefore always returns `False`.
- **Suggested fix:** give the resolver one way to learn a provider verdict — e.g. pass the resolver into the provider services and call `resolver.mark_unavailable(source, source_id, reason)` from `_mark_unavailable`, or move the negative memo into the resolver and have the provider consult it. Also reconcile the key spaces (a provider track id is not a `source:source_id` pair).
- **Fix side effects:** the resolver's `_FAIL_TTL` is 120 s while the provider's is 3600 s — wiring the provider into the resolver would shorten the memo to 2 minutes unless `_FAIL_TTL` is raised, and a too-short TTL re-opens the "re-resolve a dead track" loop that `core/resolver.py:24-26` was written to prevent.
- **Discovered by:** B

#### F-WN-15-3  [P2] — `StreamResolver` is not the resolution authority: three of the four resolution paths bypass `resolve()` and only write back into its cache

- **File:** `core/resolver.py:165-230` (the single-flight path); bypasses at `core/app.py:296-506`, `core/proxy.py:1051`, `core/playback_recovery.py:127-128`, `core/playback_recovery.py:156-157`
- **Confirmed:** yes
- **Description:** the actual call graph is four separate paths that each talk to a provider directly:

  | # | Entry | Provider call | Goes through `StreamResolver.resolve()`? | Writes back? |
  |---|---|---|---|---|
  | 1 | `AppApi.play_track` → `AppApi._resolve_track` → `AppCore.re_resolve_stream_url_async` | `core/app.py:502` `service.get_stream_url(url, ...)` | **no** | yes — `core/app.py:354` `self.resolver.refresh(...)` |
  | 2 | `AudioEngine.resolve_stream_url` (prefetch, proxy) | `audio/engine.py:205/317/363/393/444/503` | **yes** | yes — `core/resolver.py:256` `_persist` |
  | 3 | proxy 403/410 self-heal | `core/proxy.py:1051` `re_resolve_stream_url_async(...)` | **no** | yes — via path 1 |
  | 4 | `AppApi.recover_stream` → `core.playback_recovery.recover_stream` | `core/playback_recovery.py:128` / `:157` | **no** | yes — `core/playback_recovery.py:179` `resolver.refresh(...)` |

  Path 1 is the **primary user-initiated playback path** and it never enters the resolver's single-flight, never consults `_failed`, and never benefits from the in-memory tier — it does its own `db.get_cached_stream()` (`core/api.py:1676`). The resolver's docstring ("Single-flight: concurrent requests for the same (source, source_id) share one background resolution instead of each triggering the full network cascade", `core/resolver.py:7-8`) therefore only describes path 2.
- **Cause:** the resolver was introduced as a cache layer ("mem → DB → network", `core/resolver.py:4-5`) but the provider-facing orchestration stayed in `AppCore.re_resolve_stream_url_async`; the resolver was bolted on around one of its four callers.
- **Trigger conditions:** every playback. Two concurrent plays/prefetches of the same track hit paths 1 and 2 at once and both run the cascade. They converge only by accident, at the provider's own `_join_request` fan-out (`services/base_service.py:140-161`), keyed on the provider URL — a *different* key space from the resolver's `(source, source_id)`.
- **User impact:** duplicated extraction work on every race (the resolver's `network_cascades` statistic under-reports the real cost — it counts only path 2); inconsistent caching semantics (path 1 reads the DB with the default 4 h window, path 2 reads mem-then-DB); and the resolver's stats/`is_unavailable` cannot describe what the app actually did. Concretely, `core/resolver.py:188-194` re-checks the mem cache under the lock precisely to avoid "prefetch + Play extract the same track twice" — but Play (path 1) never reaches that code.
- **Evidence:**
  ```python
  # core/app.py:499-502  (path 1: the bridge play path calls the provider directly)
                  if offline_result():
                      return
                  service.get_stream_url(url, callback=_on_resolved, error_callback=_on_err, quality=quality)
  ```
  ```python
  # core/playback_recovery.py:127-128  (path 4: recovery also calls the provider directly)
          stream, metadata = _callback_result(
              lambda done, failed: service.get_stream_url(target, callback=done, error_callback=failed),
  ```
  ```python
  # core/resolver.py:7-8 (the contract that is only true for one of the four paths)
  Single-flight: concurrent requests for the same (source, source_id) share one
  background resolution instead of each triggering the full network cascade.
  ```
- **Reproduction / verification:** grep the provider entry points — `core/app.py:502`, `core/playback_recovery.py:128`, `core/playback_recovery.py:157` — and confirm none of them is inside `StreamResolver.resolve()`. Cross-check `core/api.py:1604` and `core/api.py:1744`, which both call `self._core.re_resolve_stream_url_async(...)` rather than `resolver.resolve(...)`.
- **Suggested fix:** make `AppCore.re_resolve_stream_url_async` delegate to `StreamResolver.resolve()` (keeping the callback shape), and route the proxy self-heal and `recover_stream` through the same entry point. Then the resolver really is the single authority and its single-flight, negative cache and stats describe reality.
- **Fix side effects:** `resolve()` is **synchronous** (it blocks the caller for the whole cascade), while `re_resolve_stream_url_async` is callback-based on a background thread. Converting path 1 to `resolve()` requires keeping the worker thread in `AppCore` — a naive conversion would block the pywebview bridge thread on a 30 s cascade.
- **Discovered by:** B

#### F-WN-15-4  [P2] — `recover_stream` destroys the cached URL before it knows whether recovery can succeed, and runs outside the single-flight

- **File:** `core/playback_recovery.py:120`, `core/playback_recovery.py:77-92`, `core/playback_recovery.py:177-181`; retry ladder in `ui/web_new_v2/js/player.js:448-493`
- **Confirmed:** yes
- **Description:** `recover_stream` calls `_invalidate(core, source, track, target)` **before** it attempts any resolution (`core/playback_recovery.py:120`). `_invalidate` drops the resolver's in-memory entry (`core/resolver.py:248-249`) **and** NULLs the DB row (`core/resolver.py:252` → `core/database.py:2221` `UPDATE stream_cache SET stream_url = NULL`). If the network is down, the recovery fails and the track is left with **no cached URL at all** — the next play must re-run the whole cascade from scratch. In addition, recovery calls the provider directly (path 4 in F-WN-15-3), so two concurrent recoveries of the same track both run a full cascade.
- **Cause:** invalidate-then-resolve was chosen to defeat a stale-cache 403 loop, but the invalidation is unconditional and is not rolled back when the recovery fails.
- **Trigger conditions:** the recovery ladder fires on any `<audio>` error or a 10 s stall (`js/player.js:437`, `:510-518`), up to 2 attempts per track (`js/player.js:462`). With the network down, every failure also destroys the cache, so the *next* play is a cold cascade rather than a cache hit.
- **User impact:** a transient outage converts every cached track into an uncached one, so the outage lasts longer than it should: after the network returns, the first play of each track pays a full resolution instead of a cache hit. `_invalidate` also pops from the **process-wide** `BaseMusicService._stream_cache` by URL match (`core/playback_recovery.py:86-92`), so an unrelated track that happens to share the URL loses its provider-cache entry too.
- **Evidence:**
  ```python
  # core/playback_recovery.py:119-121
      target = _target(source, track)
      _invalidate(core, source, track, target)
      deadline = time.monotonic() + 18.0
  ```
  ```python
  # core/playback_recovery.py:86-92  (the shared provider cache is pruned by URL match)
      dead_urls = {cached, track.get("file_path"), track.get("stream_url")}
      with BaseMusicService._cache_lock:
          for key, entry in list(BaseMusicService._stream_cache.items()):
              data = entry.get("data", entry) if isinstance(entry, dict) else {}
              url = data.get("stream_url") if isinstance(data, dict) else None
              if key in (f"{source}:{identifier}", f"{source}:{target}") or (url and url in dead_urls):
                  BaseMusicService._stream_cache.pop(key, None)
  ```
- **Reproduction / verification:** with a stub provider that always errors, call `recover_stream(core, track)` twice and observe `core.resolver.get_cached_url(source, id)` → `None` and `db.get_cached_stream(source, id)['stream_url']` → `None` after the first failed attempt, even though a valid URL was cached before the call.
- **Suggested fix:** only invalidate after a successful re-resolution (or snapshot the old URL and restore it on failure); and route the recovery's provider call through the resolver so it inherits the single-flight.
- **Fix side effects:** restoring the old URL on failure re-introduces the stale-URL 403 loop the invalidate was added to break — the restore should be conditional on the old URL not being `stream_url_expired()`.
- **Discovered by:** B

#### F-WN-15-5  [P2] — Fully-signed provider URLs are persisted in plaintext with a 24 h row lifetime and are re-emitted to the WebView

- **File:** `core/resolver.py:256-267` (persist), `core/database.py:2162-2197` (`cache_stream`), `core/database.py:311-327` (schema), `core/api.py:1723` + `core/api.py:1200` + `core/api.py:1240` (bridge payload), `ui/web_new_v2/js/player.js:1693-1694` (direct playback)
- **Confirmed:** yes
- **Description:** `StreamResolver._persist()` stores the **complete signed provider URL** — including the CDN signature, the expiry epoch and the client IP binding — into the user's SQLite file in clear text:
  ```python
  # core/resolver.py:263-267
          if self._db is not None:
              try:
                  self._db.cache_stream(source, str(source_id), url)
              except Exception as e:
                  logger.debug(f"Failed to cache stream URL: {e}")
  ```
  `core/database.py:2181-2194` writes it verbatim into `stream_cache.stream_url TEXT` and stamps the row with `expires_at = datetime('now', '+24 hours')` — **four times** the ~6 h validity of a googlevideo URL and **24×** the resolver's own 1 h in-memory TTL. `core/playback_recovery.py:179` does the same via `resolver.refresh()`.

  The same raw URL then crosses into the WebView: `core/api.py:1723` `track["file_path"] = stream_url` (and `:1591`), `core/api.py:1200` `track_copy = dict(track)`, `core/api.py:1240` `self._emit("track_changed", track_copy)` — the payload carries the raw signed URL in `file_path`. `ui/web_new_v2/js/player.js:1693-1694` will even hand it straight to the `<audio>` element (`playTrack(track, track.file_path)`), bypassing the loopback proxy that exists precisely to keep provider credentials on the Python side (`WIN_AUDIT_CONTEXT.md:22-23`).
- **Cause:** the resolver treats a provider URL as an opaque cache value and has no notion of "part of this URL is a bearer credential". There is no scrub/encrypt/redact boundary anywhere between the provider and the three sinks (DB, log, bridge payload).
- **Trigger conditions:** every successful resolution.
- **User impact:** a bearer-equivalent signed CDN URL sits in `~/.nedotify/nedotify_storage.db` for up to a day (readable by anything that can read the user's profile, and copied verbatim if the user shares the DB for support), and lives in the WebView's JS heap / DOM. The URL is IP-bound and time-limited, so the exposure window is bounded — but the *row* lifetime is not aligned with it.
- **Evidence:**
  ```python
  # core/database.py:2179-2194
                      cursor.execute(
                          """
                          INSERT INTO stream_cache
                          (source, source_id, stream_url, title, artist, cover_url, duration, metadata_json, cached_at, expires_at)
                          VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, datetime('now', '+24 hours'))
                          ON CONFLICT(source, source_id) DO UPDATE SET
                              ...
                              expires_at = datetime('now', '+24 hours')
                      """,
  ```
  ```python
  # core/api.py:1722-1723  (the raw URL enters the track dict)
                  logger.info(f"api.py -> on_resolved! stream_url={stream_url[:80]}")
                  track["file_path"] = stream_url
  ```
- **Reproduction / verification:** resolve one track, then `SELECT source, source_id, stream_url, expires_at FROM stream_cache;` — the row contains the full `googlevideo.com/videoplayback?...&sig=...&pot=...` URL and `expires_at` is now +24 h. The same string is visible in the `track_changed` payload received by `window.onPythonEvent` (devtools console in the WebView, or `core/api.py:1240`).
- **Suggested fix:** store only the non-secret part of the URL plus a provider-specific refresh handle, or at minimum align the row's `expires_at` with the URL's own `expire` parameter instead of a flat +24 h; and strip `file_path` from the `track_changed` payload (the frontend only needs `stream_url`, which is already a proxy URL).
- **Fix side effects:** shortening `expires_at` to the URL's own expiry changes `core/offline.py:55`, which reads the cache with `max_age_seconds = 2**31 - 1` specifically to find `cached_file_path` rows — that lookup must keep working for downloaded files, so the expiry must only govern the `stream_url` column, not the row.
- **Discovered by:** B

#### F-WN-15-6  [P2] — `core/offline.py::available_tracks` full-scans the `stream_cache` table on every offline listing, and rows with a cached file are never purged

- **File:** `core/offline.py:62-73`, `core/database.py:2227-2241`, `core/database.py:311-327`; callers at `core/api.py:483`, `core/api.py:1445`, `core/api.py:2150`, `core/api.py:2564`, `core/api.py:2730`, `core/api.py:4147`, `services/smart_playlists.py:166`
- **Confirmed:** yes
- **Description:** `available_tracks()` materialises the **entire** cached-file map before it looks at a single requested track:
  ```python
  # core/offline.py:62-64
  def available_tracks(db, tracks):
      cached = {(row['source'], str(row['source_id'])): row['cached_file_path']
                for row in db.conn.execute('SELECT source, source_id, cached_file_path FROM stream_cache WHERE cached_file_path IS NOT NULL')}
  ```
  `stream_cache` has **no index on `cached_file_path`** (`core/database.py:350-356` indexes only `tracks`), so this is a full table scan. The table grows monotonically because the purge explicitly *skips* the rows that matter:
  ```python
  # core/database.py:2234-2237
                      cursor.execute(
                          "DELETE FROM stream_cache WHERE expires_at IS NOT NULL "
                          "AND datetime(expires_at) < datetime('now') "
                          "AND (cached_file_path IS NULL OR cached_file_path = '')"
                      )
  ```
  i.e. every row that has a `cached_file_path` (one per downloaded/cached track) is kept forever.
- **Cause:** the offline helper was written for a small table and was never re-checked against the table's actual growth rule; the purge was scoped to URL-only rows.
- **Trigger conditions:** any call to `available_tracks()` — i.e. every offline-mode play with a queue (`core/api.py:1445`), every offline search (`core/api.py:2150`), every favourites listing (`core/api.py:2730`), every album view (`core/api.py:483`), every smart-playlist evaluation (`services/smart_playlists.py:166`), and every offline-mode toggle (`core/api.py:4147`).
- **User impact:** a library with a few thousand downloaded tracks makes every one of those operations scan and materialise thousands of rows (a dict of N entries plus N `sqlite3.Row` objects) on the bridge thread — visible as a stall in the UI when the user opens the favourites list or searches while offline. The table also grows without bound, so the cost is monotonic over the app's lifetime.
- **Evidence:** quoted above. The `UNIQUE(source, source_id)` index (`core/database.py:324`) makes the *point* lookups in `available_track()` cheap; the problem is exclusively the pre-built whole-table map in `available_tracks()`.
- **Reproduction / verification:** `SELECT COUNT(*) FROM stream_cache WHERE cached_file_path IS NOT NULL;` after a normal session, then time `available_tracks(db, tracks)` — the cost tracks the row count, not the number of requested tracks.
- **Suggested fix:** replace the pre-built map with per-track indexed lookups (`db.get_cached_stream(source, source_id, max_age_seconds=2**31-1)` per track, as `available_track()` already does) or add an index on `cached_file_path`; separately, give `cleanup_expired_cache` a rule for `cached_file_path` rows whose file no longer exists on disk.
- **Fix side effects:** per-track lookups turn one scan into N index seeks — cheaper for small `tracks` lists, slightly worse for very large ones; a `cached_file_path IS NOT NULL` partial index would make the map cheap again without changing the shape.
- **Discovered by:** B

#### F-WN-15-7  [P2] — Offline mode is a scattered `if`, not a policy layer: the resolver has no offline awareness and the proxy's `/?url=` branch has no offline gate

- **File:** `core/resolver.py` (whole file — no `is_offline` import), `audio/engine.py:121-151`, `core/proxy.py:814` vs `core/proxy.py:863-940`, `core/playback_recovery.py:113` vs `core/playback_recovery.py:131/137/149/166`, `core/api.py:461-512`
- **Confirmed:** yes (code paths); the user-visible frequency is a hypothesis
- **Description:** `core/offline.py` provides the right abstraction (`is_offline()`, `available_track()`, `available_tracks()`), and the bridge enforces offline centrally via `_offline_bridge_result` (`core/api.py:461-512`, wired to every public bridge method at `core/api.py:401-444`; `prefetch_track` is explicitly listed at `core/api.py:502`). That part is good. The gap is below the bridge:

  1. **`core/resolver.py` never consults offline state.** Neither does `audio/engine.py::resolve_stream_url` (`audio/engine.py:121-151`). Any caller that reaches `StreamResolver.resolve()` performs a full network cascade regardless of the mode.
  2. **The proxy's `/api/stream` branch has an offline gate (`core/proxy.py:814`); the proxy's `/?url=` branch (`core/proxy.py:863-940`) has none.** In offline mode that branch still fetches the upstream CDN URL, and it can call `engine.resolve_stream_url()` at `core/proxy.py:899` and `core/proxy.py:925` — i.e. it can trigger a full network cascade in offline mode.
  3. **`core/playback_recovery.py:113` re-implements the predicate inline** although the same file imports `is_offline` and uses it four lines later:
     ```python
     # core/playback_recovery.py:112-114
         settings = getattr(core, "settings", None)
         if settings and settings.get("network", "offline_mode", False):
             return {"ok": False, "code": "offline", "error": "Трек не скачан. ..."}
     ```
     The inline test and `is_offline()` disagree for the string values `'1'` and `'0'`: the inline test says "offline", `is_offline()` says "online". (`SettingsManager.get` coerces only `'true'`/`'false'` — `core/settings.py:394-399` — so `'1'`/`'0'` survive the round trip, and `AppApi.save_setting` (`core/api.py:2940`) accepts an arbitrary value for any key.)
- **Cause:** offline mode was implemented as an interception at each entry point rather than as a policy object consulted by the components that actually touch the network.
- **Trigger conditions:** (1) and (2) whenever offline mode is on and a `/?url=`-style proxy request arrives with a stale/remote URL; (3) whenever `network.offline_mode` is stored as `'1'`/`'0'` (reachable through the generic `save_setting` bridge method; the current UI stores a bool, so this is latent).
- **User impact:** offline mode can still pull bytes from a CDN, contradicting the user's expectation ("only saved music") and the app's own error copy ("В офлайн-режиме доступна только сохранённая музыка"). For (3), the user sees "Трек не скачан. Подключитесь к сети…" while every other part of the app believes the app is online — recovery is refused for a track that could have been renewed.
- **Evidence:** quoted above. Probe §4 confirms the predicate divergence (`stored='1'` → raw-truthy `True`, `is_offline()` `False`; same for `'0'`).
- **Suggested fix:** move the offline decision into one place — e.g. `StreamResolver.resolve()` refuses (or serves only local files) when offline, and the proxy's `/?url=` branch gains the same gate the `/api/stream` branch already has; replace the inline check at `core/playback_recovery.py:113` with `is_offline(settings)`.
- **Fix side effects:** putting the gate inside the resolver changes the meaning of "resolve" for callers that legitimately want a network URL while offline (none today) — the gate should return a distinguishable "offline" answer, not `None`, or the UI loses the "Трек не скачан" message.
- **Discovered by:** B

#### F-WN-15-8  [P2] — The proxy's request-line redaction covers `k=`/`auth_token=` but not `url=`, which carries the whole signed provider URL

- **File:** `core/proxy.py:488-489`, `core/proxy.py:1304-1316`, `core/api.py:1589`, `core/api.py:1545`, `core/api.py:1687`, `core/proxy.py:963`
- **Confirmed:** code path yes; active leak no (see below)
- **Description:** the proxy's only access log redacts exactly two query parameters:
  ```python
  # core/proxy.py:488-489
      def log_message(self, format, *args):
          logger.debug(re.sub(r'([?&](?:k|auth_token)=)[^&\s"]*', r'\1***', format % args))
  ```
  but the `?url=` form of the proxy URL embeds the **entire signed provider URL**:
  ```python
  # core/proxy.py:1304-1316
      def get_proxy_url(self, source, source_id, original_url=None, track_id=None):
          if not self.port:
              return original_url or ''
          if original_url and not _host_matches(_host_of(original_url), ('youtube.com', 'youtu.be', 'soundcloud.com')):
              params = {
                  'url': original_url,
  ```
  A `googlevideo.com` URL is not in that host list, so it takes the `?url=` branch and lands in the request line verbatim — signature, expiry and IP binding included — and the redaction list does not cover it.
- **Cause:** the redaction list was written for the proxy's own bearer token; the second, far more sensitive credential in the same query string was not considered.
- **Trigger conditions:** the `log_message` output is emitted at `logger.debug`, and `main.py:104-105` sets `logging.basicConfig(level=logging.INFO)` — so **today the line is not written at all**. The finding is that the redaction is incomplete *relative to the data the same line carries*: any future change that raises the level to DEBUG (a standard diagnostic step, and the level is global) writes bearer-equivalent signed URLs into `~/.nedotify/logs/app.log`, which rotates at 2 MB × 3.
- **User impact:** currently none. After any DEBUG bump: the log file accumulates signed CDN URLs that grant audio access to that IP for the URL's remaining lifetime.
- **Evidence:** quoted above. Separately, the INFO-level logs leak a truncated prefix of the same URL at four places (`core/api.py:1589`, `:1545`, `:1687`, `:1722` — `stream_url[:80]`) and at one WARNING (`core/proxy.py:963` — `target_url[:120]`). The 80/120-character truncations are magic numbers that happen to fall short of a googlevideo `sig` (which sits behind `expire`, `ei`, `ip`, `ipbits`, `id`, `itag`, `source`, `requiressl`, `rn`, `s`) but **not** short of a SoundCloud media URL's leading `client_id` (`https://api-v2.soundcloud.com/media/soundcloud:tracks:<id>/<hash>/stream/progressive?client_id=…`) or a Yandex URL's leading parameters.
- **Reproduction / verification:** `python -c "import logging; logging.getLogger('core.proxy').setLevel(logging.DEBUG)"` (or any DEBUG-level diagnostic run) and make one stream request; inspect `~/.nedotify/logs/app.log` for `videoplayback?...&sig=`. Conversely, confirm today's silence with `Select-String -Path "$env:USERPROFILE\.nedotify\logs\app.log" -Pattern "videoplayback"` (no hits at INFO).
- **Suggested fix:** extend the redaction to `url=` (and any other parameter that carries a provider URL), and make the INFO-level `stream_url[:N]` logs print the *host* rather than a prefix of the URL.
- **Fix side effects:** redacting `url=` makes the access log much less useful for debugging "which CDN URL was served" — printing the host plus the URL's `expire` keeps most of the diagnostic value.
- **Discovered by:** B

#### F-WN-15-9  [P3] — Four different TTLs govern the same stream URL, and the DB row outlives the URL it holds

- **File:** `core/resolver.py:20`, `core/resolver.py:23`, `core/database.py:2183`, `services/base_service.py:131`, `services/soundcloud_service.py:83`, `utils/stream_urls.py:7-26`
- **Confirmed:** yes
- **Description:** one resolved URL is governed by five different lifetimes:

  | Tier | TTL | Where |
  |---|---|---|
  | `StreamResolver._mem` | 3600 s | `core/resolver.py:20` |
  | `StreamResolver` DB read window (`_DB_MAX_AGE`) | 14400 s | `core/resolver.py:23` |
  | `stream_cache` row lifetime (`expires_at`) | **86400 s** | `core/database.py:2183` |
  | `BaseMusicService._stream_cache` | 21600 s | `services/base_service.py:131` |
  | `SoundCloudService._unavailable_cache` | 3600 s | `services/soundcloud_service.py:83` |

  The DB row (24 h) is 6× the resolver's memory TTL and 4× the resolver's own read window; `core/offline.py:55` then reads that table with `max_age_seconds = 2**31 - 1` — i.e. **no age limit at all**. A row can therefore still be "fresh" 23 hours after the signed URL it holds stopped working.
- **Cause:** each tier was added by a different change with its own rationale, and no single expiry policy was derived from the URL's own `expire` parameter.
- **Trigger conditions:** any track resolved more than 4 h before the read; any track read through `core/offline.py`.
- **User impact:** the effective guard against a stale URL is `utils/stream_urls.py::stream_url_expired`, which only understands two parameter names (`expire`, `Expires`) — a SoundCloud media URL has neither, so a dead SoundCloud URL is served until the 1 h memory TTL or the 24 h row lifetime runs out, and every play of it pays a 403 + proxy self-heal round trip.
- **Evidence:** the table above; `core/database.py:2183` `VALUES (..., CURRENT_TIMESTAMP, datetime('now', '+24 hours'))`; `core/offline.py:55` `cached = db.get_cached_stream(source, str(source_id), max_age_seconds=2 ** 31 - 1)`.
- **Reproduction / verification:** resolve a track, `UPDATE stream_cache SET cached_at = datetime('now','-20 hours')`, then read it back with `get_cached_stream(source, id)` — it is still returned, and `expires_at` is still in the future.
- **Suggested fix:** derive one expiry per entry — the minimum of the URL's own `expire` and a policy cap — and use it for the memory TTL, the DB row and the read window; make `core/offline.py`'s age-free read a targeted `cached_file_path` lookup rather than a whole-row read.
- **Fix side effects:** shortening the DB window means `core/api.py:1676` (`db.get_cached_stream(source, source_id)` with the default 4 h) and `core/proxy.py:796` will start missing rows that the provider cache still holds — the tiers must be aligned together or the miss rate will rise.
- **Discovered by:** B

#### F-WN-15-10  [P3] — `same_recording` silently skips its duration guard when either side has no duration, so a different recording can be substituted and then cached under the original track's key

- **File:** `core/playback_recovery.py:14-37` (esp. `:30-36`), `core/playback_recovery.py:133-134`, `core/playback_recovery.py:160-161`, `core/playback_recovery.py:179`
- **Confirmed:** yes
- **Description:** `same_recording()` is the only thing standing between "renew this stream" and "play a different song". Two of its guards are conditional on data being present:
  ```python
  # core/playback_recovery.py:30-36
      try:
          expected = float(wanted.get("duration") or 0)
          actual = float(offered.get("duration") or 0)
      except (ValueError, TypeError):
          return False
      if expected and actual and abs(expected - actual) > max(4.0, expected * 0.025):
          return False
      return True
  ```
  If `offered` has no `duration` (or `wanted` has none), the duration check is **skipped entirely**, and the artist check at `:28-29` is skipped when the wanted track has no artist. What remains is `similarity(base_title) ≥ 0.88` (a `SequenceMatcher` ratio, `services/music_matching.py:27-35`) plus an exact `version` match.
- **Cause:** the guard was written as "compare the durations *if* both are known", but the comparison is the strongest signal that two recordings are the same take; treating it as optional removes it exactly when the metadata is thinnest.
- **Trigger conditions:** a provider search result or a direct extraction whose metadata lacks `duration` — which is common for SoundCloud search results (the fast API path builds `duration` at `soundcloud_service.py:707`, but the yt-dlp fallback path and several provider payloads do not always carry it) and for the `wanted` track when the row in `tracks` has `duration = 0`.
- **User impact:** the recovery silently swaps in a different recording (a live take, a cover, a sped-up edit) for the track the user asked for, and then `core/playback_recovery.py:179` `resolver.refresh(source, identifier, stream)` **caches that URL under the original track's key** — so the wrong recording becomes the cached stream for the original track and is served by the normal play path afterwards. The user hears the wrong song and the cache now points at it.
- **Evidence:** quoted above; `core/playback_recovery.py:179` `resolver.refresh(source, identifier, stream)`; note that `selected_source`/`selected_id` may differ from `source`/`identifier` when the fallback provider was used, so the row's `source` column can even disagree with the URL it holds.
- **Reproduction / verification:** verified directly against the repo's own matcher (`& ".venv_win\Scripts\python.exe"`, `from core.playback_recovery import same_recording`):

  | wanted | offered | `same_recording` |
  |---|---|---|
  | `{title:'Song', artist:'Artist', duration:240}` | `{title:'Song', uploader:'Artist'}` — **no duration** | **`True`** (guard skipped) |
  | `{title:'Song', artist:'Artist', duration:240}` | `{title:'Song', uploader:'Artist', duration:0}` | **`True`** (guard skipped) |
  | `{title:'Song', artist:'Artist', duration:240}` | `{title:'Song', uploader:'Artist', duration:400}` | `False` (guard fires) |
  | `{title:'Song', artist:'Artist', duration:240}` | `{title:'Song', uploader:'Someone Else', duration:240}` | `False` (artist guard fires) |
  | `{title:'Song', artist:'Artist', duration:240}` | `{title:'Song (Acoustic)', uploader:'Artist', duration:240}` | `False` (version guard fires) |

  The first two rows are the defect: with no duration on the candidate the check that would have rejected a different take is simply not evaluated. (`similarity('Song','Song!') == 1.0` — `services/music_matching.py:27-35` normalises punctuation away — so a re-recorded "Song!" also passes the title gate.)
- **Suggested fix:** treat a missing duration as a *failure* of the match (or require an explicit "unknown duration" allowance from the provider), and record the matched candidate's identity in the cache key instead of reusing the original `source`/`source_id`.
- **Fix side effects:** requiring a duration will reject legitimate matches for providers that never report one — the fix needs a provider-supplied confidence flag rather than a blanket requirement.
- **Discovered by:** B

#### F-WN-15-11  [P3] — `recover_stream` holds the process-wide provider cache lock while copying the entire 2000-entry provider cache

- **File:** `core/playback_recovery.py:87-92`, `services/base_service.py:125-127`, `services/base_service.py:194/219/251/268`
- **Confirmed:** yes
- **Description:** `_invalidate()` prunes the **class-level, shared** `BaseMusicService._stream_cache` under the global `_cache_lock`, and it does so by materialising the whole cache first:
  ```python
  # core/playback_recovery.py:87-92
      with BaseMusicService._cache_lock:
          for key, entry in list(BaseMusicService._stream_cache.items()):
              data = entry.get("data", entry) if isinstance(entry, dict) else {}
              url = data.get("stream_url") if isinstance(data, dict) else None
              if key in (f"{source}:{identifier}", f"{source}:{target}") or (url and url in dead_urls):
                  BaseMusicService._stream_cache.pop(key, None)
  ```
  `BaseMusicService._cache_lock` is a single class-level `RLock` shared by **every** provider (`services/base_service.py:125`) and by `lyrics_lookup`, `recommendation_service` and `yandex_service`. `list(...items())` on a 2000-entry dict allocates 2000 tuples while the lock is held.
- **Cause:** the invalidation needs a global view ("is this URL cached under a different key?"), but it takes the global lock to get it.
- **Trigger conditions:** every `recover_stream()` call — and `recover_stream` calls `_invalidate` twice when the fallback provider is used (`core/playback_recovery.py:120` and `:155`).
- **User impact:** every provider's `get_from_cache`/`set_to_cache` (`services/base_service.py:194/219`) blocks for the duration of the copy — sub-millisecond at 2000 entries, but the lock is process-wide and the scan is O(cache size) on the recovery path, which is exactly the path the user is waiting on during an audio error.
- **Evidence:** quoted above; `_MAX_CACHE_SIZE = 2000` at `services/base_service.py:127`.
- **Suggested fix:** build the URL→key index once at class level (or maintain a reverse map) so the invalidation can drop the two known keys without a full scan, and take the lock only for the mutation.
- **Fix side effects:** a reverse index must be kept in sync with `_cache_cache_recent`'s eviction, which is duplicated in several places (`services/base_service.py:224-241`).
- **Discovered by:** B

#### F-WN-15-12  [P3] — `playback_recovery.py` re-implements the offline predicate inline instead of using the `is_offline()` helper it already imports

- **File:** `core/playback_recovery.py:11`, `core/playback_recovery.py:112-114` vs `core/playback_recovery.py:131`, `:137`, `:149`, `:166`
- **Confirmed:** yes
- **Description:** the file imports the shared policy helper and then uses it four times — but the *first* check, the one that decides whether recovery is attempted at all, uses an inline truthiness test:
  ```python
  # core/playback_recovery.py:11
  from core.offline import is_offline
  ...
  # core/playback_recovery.py:112-114
      settings = getattr(core, "settings", None)
      if settings and settings.get("network", "offline_mode", False):
          return {"ok": False, "code": "offline", "error": "Трек не скачан. ..."}
  ```
  The two predicates disagree for the string values `'1'` and `'0'` (inline → offline, `is_offline()` → online); `SettingsManager.get` coerces only `'true'`/`'false'` (`core/settings.py:394-399`), and `AppApi.save_setting` (`core/api.py:2940`) writes arbitrary values for any key, so a `'1'` survives the round trip.
- **Cause:** the check was written before `is_offline()` was introduced and was never migrated.
- **Trigger conditions:** `network.offline_mode` stored as `'1'`/`'0'` rather than a bool. The current UI (`ui/web_new_v2/js/feature-controls.js:14`) stores a bool and `AppApi.set_offline_mode` (`core/api.py:4132-4134`) rejects non-bools, so this is latent today.
- **User impact:** with the value stored as `'1'`, `recover_stream` refuses with "Трек не скачан. Подключитесь к сети…" while `is_offline()` reports online everywhere else — the recovery is refused for a track that could have been renewed, and the app's own offline state is inconsistent with itself.
- **Evidence:** quoted above; probe §4 prints the divergence table.
- **Suggested fix:** replace the inline test with `is_offline(settings)` (the helper is already imported) — one line.
- **Fix side effects:** none; `is_offline()` is a superset of the intended semantics and is what every other caller uses.
- **Discovered by:** B

---

### 3. Clean areas

Checked and found correct — no findings raised:

- **AGENTS.md lock rule (in-memory tier).** `core/resolver.py:49` `self._lock = threading.Lock()` and every access to `_mem` (L50), `_inflight` (L51), `_failed` (L52) and `_stats` (L53) happens under that one lock — `_mem_set` (L64-77), `_mark_failed` (L79-84), `_is_failed` (L86-95), `mark_unavailable` (L112-117), `clear_unavailable` (L120-122), `_mem_get` (L129-139), `get_cached_url` (L145-159), `resolve` (L188-221), `invalidate` (L248-249), `_persist` (L257-262), `stats` (L269-271). The rule "a new shared field joins its class's existing lock" is satisfied: no second lock was opened for `_inflight`.
- **No lock-order inversion.** The resolver never touches `BaseMusicService._cache_lock`, and `core/playback_recovery.py::_invalidate` releases the resolver lock before taking the provider cache lock (`core/playback_recovery.py:82-87`): the observed order is `resolver._lock` → `db._write_lock` (released), then `_cache_lock` — never nested in the opposite direction. `core/database.py`'s `_write_lock` (an `RLock`) is only ever the innermost lock.
- **No callback is invoked while the resolver lock is held.** `resolver_fn()` is called at `core/resolver.py:211`, *after* the `with self._lock:` block ends at L208; `flight.event.set()` (L222) is also outside the lock; `_mem_get`/`_mem_set`/`_mark_failed` are called only from lock-held contexts and never invoke user code.
- **The flight is removed from `_inflight` on every exit path.** `core/resolver.py:218-221` — the `finally` block pops the flight under the lock, guarded by `if self._inflight.get(key) is flight`, and `flight.event.set()` follows unconditionally. Verified empirically: after the owner completed (normally or with an exception) `len(r._inflight) == 0`. A `BaseException` (e.g. `KeyboardInterrupt`) also lands in the `finally`.
- **Re-entrancy is bounded, not a permanent deadlock.** If `resolve()` were re-entered from inside a callback, the inner call finds the outer flight in `_inflight`, is not the owner, and waits on `flight.event` — which the outer call can only set after `resolver_fn()` returns. Because `flight.event.wait(timeout=self._resolve_timeout)` is bounded, the stall is **exactly `_RESOLVE_TIMEOUT` = 12 s** and then self-heals (probe §2: inner `resolve()` returned `None` after 12.0 s, the outer then returned `'http://outer'`). No such re-entrant call path exists today.
- **The in-memory cache is bounded and LRU-correct.** `core/resolver.py:21` `_MEM_MAX_SIZE = 1024`; `_mem_set` (L64-77) drops the key first (to refresh recency) and evicts the oldest insertion; `_mem_get` (L129-139) re-inserts on a hit with the **original** timestamp, so a hit refreshes recency but not the TTL (pinned by `tests/test_cache_lru.py:204`). Measured cost: ≈827 bytes per entry (key tuple + value tuple + a 600-char URL string) → ≈0.81 MB for a completely full cache. Overflow behaviour verified: 1074 inserts leave exactly 1024 entries.
- **The negative cache is bounded.** `core/resolver.py:28` `_FAIL_MAX_SIZE = 512` with the same oldest-first eviction (`_mark_failed`, L79-84). (It is never populated in production — see F-WN-15-2.)
- **The "unavailable" verdict is derived from permanent errors, not transient ones.** `services/soundcloud_service.py:550-567` `_media_url_is_servable` returns `True` for 5xx and transport errors and only treats 401/403/404/410 (`_MEDIA_DENIED_STATUSES`, L109) as final; the yt-dlp path re-raises anything that is not an unplayable error (`L732-733`, `_is_unplayable_error` L100-103). A network outage therefore does **not** blackhole a provider — the effective memo is capped at 200 entries × 1 h.
- **The resolver does not serialise network resolution behind its lock.** `resolver_fn()` runs with the lock released (`core/resolver.py:209-211`); the lock is only held for dictionary bookkeeping. A slow provider therefore blocks only its own callers, not other resolutions.
- **The expiry check is cheap and side-effect free.** `utils/stream_urls.py:7-26` does one `urlsplit` + one `parse_qs` and inspects two parameter names — no network probe, no DB access. It correctly requires `len(value) >= 6` so a small numeric token is not mistaken for an epoch, and it honours a 60 s margin. Verified: a past 10-digit epoch → `True`; a future epoch → `False`; `expire=1` → `False` (the length guard); `Expires=<past epoch>` → `True`.
- **`get_cached_url` does not hit the DB on every playback.** The in-memory tier is checked first (`core/resolver.py:145-148`) and absorbs the repeat reads; the DB is consulted only on a memory miss (`core/resolver.py:150-163`). The DB read itself is an index seek on `UNIQUE(source, source_id)` (`core/database.py:324`) plus a `strftime` filter on the single matching row.
- **The recovery path leaves the queue untouched.** `core/playback_recovery.py::recover_stream` never references `core.engine.queue`, `PlaybackQueue`, or the listening session — consistent with its docstring ("without changing the queue or listening session", L1). It does mutate the resolver's and the provider's caches, which is a cache effect, not a queue effect (see F-WN-15-4).
- **`recover_stream` preserves the playback position.** The position is parsed defensively (`core/playback_recovery.py:99-105`: non-finite → 0, negative → 0, rounded) and returned as `position_ms` (L182-183); the frontend applies it via `playTrack(..., {resumeMs, recovery: true})` (`ui/web_new_v2/js/player.js:483`).
- **The recovery deadline is bounded.** `core/playback_recovery.py:121` `deadline = time.monotonic() + 18.0`, and every stage is clamped by `min(<stage budget>, deadline - now)` (`:129`, `:147`, `:158`) with an explicit deadline break at `:139-140`. The per-stage budgets (8 s / 3 s / 4 s) sum to less than the 18 s deadline.
- **The provider credentials are not forwarded to foreign hosts.** `core/proxy.py:91-99` `_host_allows_credentials` requires the target host to equal or be a subdomain of the source provider's own host list (`CREDENTIAL_HOSTS`, L60-64); otherwise the cookies/OAuth token are withheld and a warning is logged (`core/proxy.py:984-989`). The SSRF guard is applied to **both** proxy branches (`core/proxy.py:841` and `:954`).
- **The proxy is fail-closed on its bearer token.** `core/proxy.py:503-511` — an unset token refuses every request; `hmac.compare_digest` is used for the comparison.

---

### 4. Coverage gaps

- **The four providers' own caches were not audited.** `services/youtube_service.py`, `services/yandex_service.py`, `services/spotify_service.py` and `services/itunes_gateway.py` were read only at the call sites that matter for WN-15 (`get_stream_url` / `set_to_cache` / `get_from_cache`). Their internal extraction logic, cookie handling and pool sizing belong to WN-19/WN-21.
- **No runtime measurement of the real network cost.** The 30 s owner budget in F-WN-15-1 is derived from the code's own `time.monotonic()` deadlines (`audio/engine.py:208/278/447/482`), not from a live capture of a slow provider; the *observed* cascade duration on a real network was not measured (the audit is not allowed to make provider round trips).
- **The proxy's DEBUG-level access log was not captured end-to-end.** The claim in F-WN-15-8 that the `url=` parameter reaches the log at DEBUG level is derived from `core/proxy.py:488-489` plus `BaseHTTPRequestHandler`'s standard request-line logging; it was not reproduced against a running proxy instance.
- **`same_recording` was not fuzzed against live provider payloads.** F-WN-15-10 identifies the missing-duration hole by reading the conditions and by calling the repo's own `same_recording()` directly (the verified table in the finding); the *end-to-end* outcome — a live provider substituting a different recording — was not demonstrated against a real provider.
- **The Yandex OAuth token was not traced end-to-end.** The token is injected as an `Authorization` header by the proxy (`core/proxy.py:1004-1006`) and does not appear in the cached URL, but whether `services/yandex_service.py`'s `direct_link` (`yandex_service.py:212`) carries a credential in its query string was not verified.
- **`core/api.py`'s frontend payload surface was not audited as a whole.** Only the fields that carry a resolved URL (`file_path`, `stream_url`) were traced; the rest of the ~200-method bridge belongs to WN-03 … WN-10.
- **The Windows-specific behaviour of SQLite file permissions was not verified** — the "readable by anything that can read the user's profile" statement in F-WN-15-5 assumes the default `%USERPROFILE%` ACL.

---

### 5. Architecture improvements (ARCH)

No proven defect — these are design proposals.

- **ARCH-1 — Make `StreamResolver` the single resolution authority.** Today four paths talk to the providers and only one goes through `StreamResolver.resolve()` (F-WN-15-3). A single entry point `resolve(source, source_id, *, callback=None)` that owns the single-flight, the negative cache, the TTL policy and the persistence would make the resolver's own docstring true, make `stats()` meaningful, and remove the four-way duplication of "read DB cache → resolve → write DB cache" (`core/api.py:1676`, `core/api.py:1533`, `core/app.py:502`, `core/proxy.py:796`). The callback shape must be preserved so the bridge stays non-blocking.

- **ARCH-2 — One expiry policy, derived from the URL.** Five lifetimes govern one URL (F-WN-15-9). A single `stream_expiry(url, now)` helper — the existing `utils/stream_urls.stream_url_expired` is half of it — should return the absolute expiry of a URL, and the memory TTL, the DB row `expires_at` and the read window should all be derived from it, with the provider's own `expire` as the source of truth. `core/offline.py:55`'s age-free read should become a targeted `cached_file_path` query.

- **ARCH-3 — Offline mode as a policy, not 20 `if`s.** `core/offline.py` already has the right shape (`is_offline`, `available_track`); what is missing is a single point where the network is actually touched. Folding the offline decision into the resolver + proxy (F-WN-15-7) turns "offline" from a scattered convention into an enforced invariant, and removes the duplicated predicate at `core/playback_recovery.py:113`.

- **ARCH-4 — A URL-secret boundary.** One function that classifies a provider URL into (a) the part that may be persisted, (b) the part that may be logged, (c) the part that may cross the bridge would close F-WN-15-5 and F-WN-15-8 at once, instead of each call site choosing its own truncation (`[:80]`, `[:120]`) and each store choosing its own lifetime.

- **ARCH-5 — Index / purge policy for `stream_cache`.** `core/offline.py:62-73` should query per track (or use an index on `cached_file_path`), and `cleanup_expired_cache` should have a rule for rows whose file has disappeared from disk — today those rows are immortal by construction (`core/database.py:2237`).

- **ARCH-6 — Disambiguate the two "resolver" concepts.** `core/resolver.py::StreamResolver` (stream URLs) and `services/track_resolver.py::TrackResolver` (title→track matching) are unrelated but share a name; `core/downloader.py:515-524` imports the latter while the playback path uses the former. A rename (`StreamResolver` → `StreamUrlResolver`, `TrackResolver` → `TrackMatcher`) would remove a real source of confusion in the call graph.

- **ARCH-7 — Give the single-flight an observable timeout budget.** F-WN-15-1 exists because the waiter budget and the owner budget live in different modules. A single constant (or a value carried on the resolver, e.g. `resolve_timeout` settable from `core/app.py`) that both the resolver and the cascade respect would remove the class of bug rather than this instance.
