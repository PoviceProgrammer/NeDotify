## AREA WN-15 — Stream resolution & playback recovery — ROLE A

### 1. Scope reviewed

**Files opened (path: line ranges actually read)**

- `core/resolver.py` — L1–271 (whole file: `_Flight` L31–37, `StreamResolver.__init__` L43–58,
  `_key` L60–62, `_mem_set` L64–77, `_mark_failed` L79–84, `_is_failed` L86–95,
  `is_unavailable` L97–99, `mark_unavailable` L101–117, `clear_unavailable` L119–122,
  `_url_expired` L124–127, `_mem_get` L129–139, `get_cached_url` L141–163, `resolve` L165–230,
  `refresh` L232–236, `invalidate` L238–254, `_persist` L256–267, `stats` L269–271)
- `core/playback_recovery.py` — L1–183 (whole file: `same_recording` L14–37, `_callback_result` L40–63,
  `_target` L66–74, `_invalidate` L77–92, `recover_stream` L95–183)
- `core/offline.py` — L1–77 (whole file: `is_offline` L10–14, `_local_file` L17–25, `_with_file` L28–32,
  `available_track` L35–59, `available_tracks` L62–73, `offline_library` L76–77)
- `utils/stream_urls.py` — L1–26 (whole file: `stream_url_expired` L7–26)

**Callers traced (read to attribute misuse to the owning area)**

- `core/api.py` — L486–512 (offline interception of the bridge), L1440–1470 (offline branch of `play_track`),
  L1510–1606 (`play_track` fast paths + DB cache), L1608–1744 (`_resolve_track`), L3640–3683 (`prefetch_track`),
  L4129–4174 (`get_offline_mode` / `set_offline_mode` / `get_offline_library` / `recover_stream`)
- `audio/engine.py` — L90–151 (`resolve_stream_url`), L153–508 (`_resolve_via_network`, incl. the 20 s
  cascade budget at L278 and every `event.wait(timeout=…)`)
- `core/proxy.py` — L790–829 (DB cache → `engine.resolve_stream_url`), L1012–1090 (403/410 self-heal:
  `resolver.invalidate` + `re_resolve_stream_url_async`), L1304–1334 (`get_proxy_url`)
- `core/app.py` — L94–150 (`StreamResolver(self.db)` at L122), L185–234 (`soundcloud` / `yandex` lazy
  properties), L296–506 (`re_resolve_stream_url_async`, incl. `resolver.refresh` at L354)
- `core/database.py` — L150–209 (per-thread connection, `row_factory = sqlite3.Row`), L300–359
  (`stream_cache` schema), L2134–2239 (`set_cached_file`, `get_cached_stream`, `cache_stream`,
  `update_cached_stream_url`, `invalidate_cached_stream`, `cleanup_expired_cache`), L1184–1210 (`get_all_tracks`)
- `services/music_matching.py` — L1–95 (`normalize`, `similarity`, `credits`, `artist_matches`, `title_metadata`)
- `services/soundcloud_service.py` — L100–169, L320–489, L520–619, L660–839 (duration units,
  `_unavailable_cache`, `_mark_unavailable`)
- `services/youtube_service.py` — L253–290, L370–515, L894–1070 (`get_stream_url` is executor-based)
- `ui/web_new_v2/js/player.js` — L430–519 (recovery retry loop), L1670–1739 (`file_path` stripped before
  `play_track`)
- `core/settings.py` — L290–449 (`SettingsManager.get/set`, string→bool normalisation)

**Callees traced into other areas (not reported here — owner named)**

- `core/app.py::re_resolve_stream_url_async` (L305–506) calls the provider **directly** and bypasses
  `StreamResolver.resolve` entirely. The single-flight, the in-memory cache and the negative cache therefore
  do **not** protect the main Play path (`core/api.py::_resolve_track` L1744) — only the proxy path
  (`core/proxy.py:817`) and `prefetch_track` go through `resolver.resolve`. **Owner: WN-02 / WN-05.**
- `services/soundcloud_service.py::_mark_unavailable` (L526–539) keeps its own 1 h "unavailable" memo
  (`_UNAVAILABLE_TTL = 3600`, L83) instead of calling `StreamResolver.mark_unavailable`. **Owner: WN-20.**
- `services/soundcloud_service.py:774` imports `core.playback_recovery.same_recording` — a service importing
  from `core/`. **Owner: WN-18 / WN-20 (architecture).**

**Verification artifacts** (scratch, outside the repo): `C:\Users\Артур\AppData\Local\Temp\opencode\audit_reports\_wn15_verify.py`,
`_wn15_verify2.py`, `_wn15_verify3.py`, `_wn15_verify4.py`. No repo file was modified.

---

### 2. Findings

#### F-WN-15-1  [P1] — A single-flight waiter gives up after 12 s while the owner's cascade may legitimately take ~30 s, so a concurrent caller is told "no stream" for a track that resolves fine

- **File:** `core/resolver.py:224` (waiter), `core/resolver.py:22` (`_RESOLVE_TIMEOUT = 12.0`),
  `core/resolver.py:209-222` (owner), `audio/engine.py:208` + `audio/engine.py:278` (cascade budget)
- **Confirmed:** yes
- **Description:** `resolve()` deduplicates concurrent requests for the same `(source, source_id)`, but only the
  *waiters* are bounded: `flight.event.wait(timeout=self._resolve_timeout)` (12 s). The *owner* runs the cascade
  with no deadline of its own, and the cascade the engine actually runs is bounded at ≈30 s
  (`event.wait(timeout=10)` for the direct YouTube attempt, then `cascade_deadline = time.monotonic() + 20.0`).
  A waiter that joins a flight which is already older than 12 s therefore returns `None` ("no stream"),
  while the owner succeeds and persists the URL a moment later.
- **Cause:** the single-flight timeout and the producer's own time budget are two independent numbers that are
  never reconciled; the waiter treats "the owner has not finished yet" as "there is no stream".
- **Trigger conditions:** any two concurrent requests for the same track while the provider is slow
  (> 12 s). The browser's `<audio>` element issues several range requests in parallel, and
  `core/proxy.py:817` resolves every one of them through `engine.resolve_stream_url` → `resolver.resolve`.
- **User impact:** the parallel stream requests are answered with HTTP 404 *"Stream not found"*
  (`core/proxy.py:820-825`) for a track that resolves 2 s later; the player then enters its error/recovery
  cycle (`ui/web_new_v2/js/player.js:448`) instead of just playing.
- **Evidence:**
  ```python
  # core/resolver.py:20-23
  _MEM_TTL = 3600.0
  _MEM_MAX_SIZE = 1024
  _RESOLVE_TIMEOUT = 12.0  # max wait for a single-flight resolution
  ...
  # core/resolver.py:223-230
  else:
      flight.event.wait(timeout=self._resolve_timeout)

  if flight.url:
      return flight.url
  if flight.error:
      logger.warning(f"Stream resolution failed for {source}:{source_id}: {flight.error}")
  return None
  ```
  ```python
  # audio/engine.py:208 / 278
  event.wait(timeout=10)
  ...
  cascade_deadline = time.monotonic() + 20.0
  ```
- **Reproduction / verification:** `_wn15_verify.py` V1 — `StreamResolver(db=None, resolve_timeout=1.0)`, two
  threads call `resolve("youtube","vid1", slow_cascade)` where `slow_cascade` sleeps 2.5 s:
  ```
  resolver_fn invocations: 1 (1 == single-flight held)
  owner result:  https://cdn.example/ok.mp3
  waiter result: None
  stats: {'mem_hits': 0, 'db_hits': 0, 'network_cascades': 1, 'single_flight_waits': 1}
  ```
  With the production constants the same happens whenever the cascade exceeds 12 s.
- **Suggested fix:** make the waiter's deadline ≥ the producer's budget (or unbounded, bounded instead by an
  explicit per-flight deadline shared by both), and/or let a timed-out waiter re-read the cache instead of
  returning `None`.
- **Fix side effects:** an unbounded waiter blocks a request thread for the full cascade; a longer timeout
  keeps the proxy's HTTP worker busy longer on a dead provider.
- **Discovered by:** A

#### F-WN-15-2  [P2] — The single-flight owner has no watchdog: a `resolver_fn` that never returns leaves the key permanently stalled

- **File:** `core/resolver.py:209-222`
- **Confirmed:** yes (mechanism confirmed by execution; reachability from today's engine is a hypothesis)
- **Description:** `_inflight[key]` is removed only in the owner's `finally` block. If `resolver_fn()` blocks
  forever, the entry stays in `_inflight` and **every** later `resolve()` for that key becomes a waiter that
  waits 12 s and returns `None` — the track can never be resolved again in that session.
- **Cause:** the timeout is applied to the waiters only; the producer has no deadline, and there is no
  reaper for abandoned flights.
- **Trigger conditions:** a `resolver_fn` that never returns. Today `audio/engine.py::_resolve_via_network`
  bounds every wait (`event.wait(timeout=10/15)`, the 20 s cascade budget), so the *current* engine cascade
  cannot hang — but `StreamResolver.resolve` is a public API and `resolver_fn` is an arbitrary caller-supplied
  callable; `audio/engine.py:149` is the only production caller today.
- **User impact:** the affected track is permanently unplayable ("Не удалось найти поток"), with a 12 s
  stall on every attempt.
- **Evidence:**
  ```python
  # core/resolver.py:209-222
  if owner:
      try:
          url, error = resolver_fn()          # <-- no timeout, no watchdog
          ...
      finally:
          with self._lock:
              if self._inflight.get(key) is flight:
                  self._inflight.pop(key, None)
          flight.event.set()
  ```
- **Reproduction / verification:** `_wn15_verify.py` V3 — owner thread with a 30 s `resolver_fn`:
  ```
  inflight while owner hangs: [('youtube', 'vid3')]
  second resolve -> None
  inflight still: [('youtube', 'vid3')]
  ```
  (V2 shows the *exception* path is clean: the flight is removed, `_inflight == {}`.)
- **Suggested fix:** give the owner a deadline (run the cascade under a watchdog and abandon the flight), or
  drop stale flights whose owner thread is gone.
- **Fix side effects:** abandoning a flight means the work is thrown away; a thread-based watchdog adds
  complexity to the hot path.
- **Discovered by:** A

#### F-WN-15-3  [P2] — `available_tracks` never consults the track row, `available_track` does: the same track is "available" to one helper and "missing" to the other, and toggling offline mode can wipe the queue or swap the current track

- **File:** `core/offline.py:62-73` (plural) vs `core/offline.py:35-59` (singular);
  caller `core/api.py:4145-4158`
- **Confirmed:** yes
- **Description:** `available_track` looks the track up in the DB (`db.get_track(int(identifier))`, L43-53) and
  uses the row's `file_path`. `available_tracks` does **not** do that lookup — it only tries the track dict's own
  `file_path` and the `stream_cache.cached_file_path` map. A downloaded track whose queue dict carries a
  *remote* `file_path` (the backend overwrites `track["file_path"] = stream_url` at `core/api.py:1723` /
  `:1729`) is therefore found by `available_track` (via the DB row) and **missed** by `available_tracks`.
  The downloader writes `tracks.file_path` (`core/downloader.py:819` / `:825`), never
  `stream_cache.cached_file_path`, so the plural helper has no other way to find it.
- **Cause:** the two helpers implement the same question with different data sources; the plural one skips the
  DB-row fallback that the singular one has.
- **Trigger conditions:** a downloaded track sitting in the queue (its dict has `id`/`track_id` and a remote
  `file_path`), then the user toggles offline mode.
- **User impact:** in `AppApi.set_offline_mode` (`core/api.py:4145-4158`) `current` is truthy but `tracks` is
  empty or missing the current entry → the queue is either **cleared** (`queue.clear()`, playback stops) or
  **reset to index 0** (`position = next((...), 0)`), i.e. the music jumps to a different track.
- **Evidence:**
  ```python
  # core/offline.py:49-53  (singular — consults the DB row)
  if stored:
      path = _local_file(stored.get('file_path'))
      if path:
          return _with_file(dict(stored, **track), path)
  ```
  ```python
  # core/offline.py:66-72  (plural — no DB-row lookup at all)
  for track in tracks:
      if not isinstance(track, dict):
          continue
      path = _local_file(track.get('file_path')) or _local_file(
          cached.get((track.get('source'), str(track.get('source_id')))), cached=True)
  ```
  ```python
  # core/api.py:4145-4158
  current = available_track(self._core.db, queue.current_track)
  active_available = current is not None
  tracks = available_tracks(self._core.db, queue.tracks)
  if current and tracks: ...
  elif tracks: ...
  else:
      queue.clear()
  ```
- **Reproduction / verification:** `_wn15_verify2.py` O1/O2 — one DB row with a real `file_path`, and a thin
  track dict `{"id": tid, "source": "youtube", "source_id": "vid1"}`:
  ```
  available_track  -> ...\song.mp3     (found via db.get_track())
  available_tracks -> []              (missed)
  => the same track is 'available' to one helper and 'unavailable' to the other: True
  ```
- **Suggested fix:** make `available_tracks` reuse `available_track` (or add the same `db.get_track` fallback),
  so both helpers answer from the same sources.
- **Fix side effects:** one extra DB lookup per queue entry — `available_tracks` is called on every offline-mode
  toggle and on every offline `play_track`, so this multiplies reads on large queues.
- **Discovered by:** A

#### F-WN-15-4  [P2] — `recover_stream` stores a stream that came from a *different* provider under the *original* `(source, source_id)` key

- **File:** `core/playback_recovery.py:177-183`
- **Confirmed:** yes
- **Description:** when the direct provider attempt fails the version check, `recover_stream` falls back to
  YouTube/SoundCloud search (`L135-165`) and may end up with a URL from another provider
  (`selected_source`/`selected_id` record which one). The final block nevertheless persists and proxies it
  under the **original** track's key: `resolver.refresh(source, identifier, stream)` and
  `proxy.get_proxy_url(source, identifier, stream, …)` use `source`/`identifier`, not
  `selected_source`/`selected_id`.
- **Cause:** the "recovered" URL and the "original track" identity are two different things, but only one pair of
  identifiers is threaded through to the cache and to the proxy.
- **Trigger conditions:** a Spotify track (its direct path is skipped, L125) or a YouTube/SoundCloud track whose
  provider result failed `same_recording` — i.e. every successful cross-provider recovery.
- **User impact:** the `stream_cache` row for e.g. `("youtube", "<original id>")` now holds a SoundCloud/YouTube
  CDN URL. The next Play reads it from the DB (`core/api.py:1676-1689`) and hands it to the player labelled
  `source="youtube"`, so the proxy fetches a foreign CDN URL under the YouTube credential/header rules. The
  provider label stored next to the URL is wrong, so any later per-provider decision (403 handling, provider
  fallback, cache invalidation) is taken against the wrong provider.
- **Evidence:**
  ```python
  # core/playback_recovery.py:162-165
  if stream:
      selected_source = fallback
      selected_id = str(candidate.get("source_id") or "")
      break
  ...
  # core/playback_recovery.py:177-183
  resolver = getattr(core, "resolver", None)
  if resolver:
      resolver.refresh(source, identifier, stream)      # <-- original key
  proxy = getattr(core, "proxy", None)
  playback_url = proxy.get_proxy_url(source, identifier, stream, track_id=track.get("id")) if proxy else stream
  return {"ok": True, "stream_url": playback_url, "position_ms": position,
          "source": selected_source, "source_id": selected_id}
  ```
- **Reproduction / verification:** `_wn15_verify4.py` — a SoundCloud fallback recovery of a YouTube track:
  ```
  response source/source_id: soundcloud right
  stream_url: http://127.0.0.1:1/?url=https://cdn.example/right.mp3
  DB row for ('youtube','original') stream_url: https://cdn.example/right.mp3
  => a soundcloud URL stored under the youtube key: True
  ```
- **Suggested fix:** key the cache/proxy entry by `selected_source`/`selected_id` (or store both the original
  identity and the resolved provider separately).
- **Fix side effects:** the proxy URL would then no longer carry the original track's identity, which the
  proxy uses to re-resolve after a 403 — that path has to be adapted.
- **Discovered by:** A

#### F-WN-15-5  [P3] — `_callback_result`'s timeout does not bound the call it is supposed to bound

- **File:** `core/playback_recovery.py:56-63`
- **Confirmed:** yes
- **Description:** `_callback_result(invoke, timeout)` calls `invoke(success, failure)` **synchronously on the
  calling thread** and only then waits on the event. The timeout therefore bounds only the *wait after* the
  provider call returned; a provider whose call blocks synchronously defeats the deadline completely.
- **Cause:** the callback API is asynchronous, but the invocation itself is made inline instead of being handed
  to a worker.
- **Trigger conditions:** a provider whose `get_stream_url` / `search` does its work inline instead of
  submitting to an executor. Today's providers are executor-based (`services/youtube_service.py:1069`,
  `services/soundcloud_service.py` `_executor.submit`), so the deadline currently holds — but the whole
  18 s budget of `recover_stream` (L121) and the per-phase 8/3/4 s limits (L129, L147, L158) rest on that
  assumption.
- **User impact:** the pywebview bridge thread that runs `AppApi.recover_stream`
  (`core/api.py:4166-4174`) stays blocked for the provider's own duration instead of the advertised budget.
- **Evidence:**
  ```python
  # core/playback_recovery.py:56-63
  try:
      invoke(success, failure)
  except Exception as error:
      failure(error)
  if not completed.wait(max(0, timeout)):
      completed.set()
      return None, {}
  return result.get("value"), result.get("metadata", {})
  ```
- **Reproduction / verification:** `_wn15_verify.py` V7 — timeout 0.2 s, `invoke` sleeps 2.0 s:
  ```
  timeout was 0.2s, invoke blocked 2.0s -> returned after 2.21s, value=None
  ```
- **Suggested fix:** run `invoke` on a worker thread so the timeout bounds the whole operation.
- **Fix side effects:** one extra thread per provider call; the provider's callback would then fire on a
  different thread than today (it already may).
- **Discovered by:** A

#### F-WN-15-6  [P3] — `stream_url_expired` only understands numeric epoch tokens, so the `Expires` form named in its own docstring is silently ignored

- **File:** `utils/stream_urls.py:7-26`
- **Confirmed:** yes
- **Description:** the helper looks for the query parameters `expire` and `Expires` but only accepts a value
  that `isdigit()`. The docstring says "signed CDN URLs can use ``Expires``", which in HTTP is normally an
  HTTP-date (`Wed, 21 Oct 2015 07:28:00 GMT`) — that value is never digit-only, so the parameter is skipped and
  the URL is treated as non-expiring. A URL with no expiry token at all is likewise reported as "not expired".
- **Cause:** the numeric test is applied to both parameter names although only one of them uses the numeric
  epoch form.
- **Trigger conditions:** a CDN URL that expresses its expiry as an HTTP date, or with no token at all.
- **User impact:** such a URL stays in the caches until the TTLs expire (memory cache 1 h, DB 4 h) instead of
  being rejected locally; a URL that dies mid-playback is only discovered by the proxy's 403 self-heal.
  The 60 s margin itself is adequate for the numeric form.
- **Evidence:**
  ```python
  # utils/stream_urls.py:18-23
  query = parse_qs(urlsplit(url).query)
  deadline = (time.time() if now is None else now) + margin
  for name in ("expire", "Expires"):
      for value in query.get(name, ()):
          if value.isdigit() and len(value) >= 6 and int(value) <= deadline:
              return True
  ```
- **Reproduction / verification:** `_wn15_verify.py` V9:
  ```
  plain CDN url:                        False
  google with expire in the future:     False
  google with expire in the past:       True
  http-date Expires param:              False   <-- not recognised
  expire within the 60s margin:         True
  ```
- **Suggested fix:** parse `Expires` as an HTTP-date (or restrict the docstring to the numeric form).
- **Fix side effects:** none — no provider in this codebase currently emits an HTTP-date `Expires`.
- **Discovered by:** A

#### F-WN-15-7  [P3] — The resolver's negative cache is never written in production; the module comment describes a behaviour that does not exist

- **File:** `core/resolver.py:24-28`, `core/resolver.py:79-122`
- **Confirmed:** yes
- **Description:** `_FAIL_TTL`, `_failed`, `_mark_failed`, `is_unavailable`, `mark_unavailable` are the
  "known unavailable" memo. `mark_unavailable` has **no production caller** anywhere in the repository — only
  `core/resolver.py` itself, `core/playback_recovery.py:85` (`clear_unavailable`) and
  `tests/test_soundcloud_drm_unavailable.py` reference it. The module-level comment at L24-27 ("A key whose
  cascade just produced nothing is skipped for this long … a DRM-protected or deleted track keeps the same
  answer for good") describes two behaviours, neither of which exists: `resolve()` never records a failure of
  its own, and a 120 s TTL cannot keep an answer "for good".
- **Cause:** the negative cache was wired up in the resolver but the providers never call it (SoundCloud keeps
  its own 1 h memo, `services/soundcloud_service.py:148`).
- **Trigger conditions:** always — the memo is simply never populated in the shipped app.
- **User impact:** a known-dead track (DRM / deleted / private) is re-resolved through the full provider
  cascade on every request; the resolver's documented short-circuit never fires.
- **Evidence:**
  ```python
  # core/resolver.py:24-28
  #: A key whose cascade just produced nothing is skipped for this long. Short on
  #: purpose: a DRM-protected or deleted track keeps the same answer for good,
  #: while a network blip is retried two minutes later instead of forever.
  _FAIL_TTL = 120.0
  _FAIL_MAX_SIZE = 512
  ```
  ```
  grep -rn "mark_unavailable" --include=*.py .
  → core/playback_recovery.py:85 (clear_unavailable), core/resolver.py:97,101,119,
    tests/test_soundcloud_drm_unavailable.py:301,308,315,327,331,339,350
  ```
- **Reproduction / verification:** `grep -rn "mark_unavailable\|is_unavailable\|clear_unavailable" --include=*.py .`
  over the repo root (excluding `android/`) — no provider or bridge method calls `mark_unavailable`.
- **Suggested fix:** either call `resolver.mark_unavailable` from the providers that can tell "this track is
  gone" from "the network hiccupped", or delete the dead memo and fix the comment.
- **Fix side effects:** wiring it up means the 120 s TTL also throttles re-checks of a track that became
  playable again; the providers' own verdict must be re-confirmed before it is trusted.
- **Discovered by:** A

#### F-WN-15-8  [P3] — A DB cache hit restarts the in-memory TTL, so a URL lives up to 5 h instead of the documented 4 h

- **File:** `core/resolver.py:152-160`
- **Confirmed:** yes
- **Description:** the DB row is accepted while `now - cached_at < _db_max_age` (4 h), and is then written into
  the in-memory cache with a **fresh** timestamp (`now`), not with the row's own age. The in-memory entry is
  therefore valid for another full `_MEM_TTL` (1 h) on top of the row's remaining life.
- **Cause:** the mem cache stores `(url, ts)` where `ts` is the *insertion* time; for a DB-sourced URL the
  insertion time is not the URL's age.
- **Trigger conditions:** any DB cache hit that is close to the 4 h limit.
- **User impact:** a stream URL can be handed out ~25 % past the documented maximum age. For YouTube
  (URL lifetime ≈ 6 h, per the comment at `core/resolver.py:23`) this is still inside the provider's own
  validity, so the practical impact is small — the proxy's 403 self-heal covers the rest.
- **Evidence:**
  ```python
  # core/resolver.py:151-160
  cached = self._db.get_cached_stream(source, str(source_id), max_age_seconds=self._db_max_age)
  if cached and cached.get("stream_url"):
      if self._url_expired(cached["stream_url"]):
          self.invalidate(source, str(source_id))
          return None
      with self._lock:
          self._mem_set(key, (cached["stream_url"], now))     # <-- 'now', not cached_at
  ```
- **Reproduction / verification:** `_wn15_verify.py` V10 — a fake DB returning a row; after
  `get_cached_url` the mem entry's age is `0.0 s`.
- **Suggested fix:** store the row's `cached_at` as the mem timestamp (or cap the mem TTL by the row's
  remaining life).
- **Fix side effects:** the mem entry then expires earlier, so slightly more DB reads.
- **Discovered by:** A

#### F-WN-15-9  [P3] — `refresh()`/`_persist()` rewrite the whole `stream_cache` row through `cache_stream`, wiping the stored title/artist/cover/duration/metadata

- **File:** `core/resolver.py:256-267` → `core/database.py:2162-2197`
- **Confirmed:** yes
- **Description:** `_persist` calls `self._db.cache_stream(source, str(source_id), url)` with the default
  empty metadata. `cache_stream`'s `ON CONFLICT` branch overwrites **all** columns
  (`title`, `artist`, `cover_url`, `duration`, `metadata_json`) with the empty defaults, so every
  re-resolution erases the metadata that was previously stored for that track.
- **Cause:** the resolver wants "set the URL"; `cache_stream` means "upsert the whole row".
- **Trigger conditions:** every successful re-resolution — `AppCore.re_resolve_stream_url_async`
  (`core/app.py:354`) and `recover_stream` (`core/playback_recovery.py:179`) both call `resolver.refresh`.
- **User impact:** latent today — no production code reads `stream_cache.title/artist/cover_url/duration`
  (only `stream_url` and `cached_file_path` are consumed: `core/api.py:1533,1676`, `core/proxy.py:796`,
  `core/offline.py:55`, `utils/cache_manager.py:306`), but the row loses data the moment a consumer appears.
- **Evidence:**
  ```python
  # core/resolver.py:263-267
  if self._db is not None:
      try:
          self._db.cache_stream(source, str(source_id), url)
      except Exception as e:
          logger.debug(f"Failed to cache stream URL: {e}")
  ```
  ```sql
  -- core/database.py:2184-2192
  ON CONFLICT(source, source_id) DO UPDATE SET
      stream_url = excluded.stream_url,
      title = excluded.title,          -- '' from resolver.refresh()
      artist = excluded.artist,        -- ''
      cover_url = excluded.cover_url,  -- ''
      duration = excluded.duration,    -- 0
      metadata_json = excluded.metadata_json,  -- NULL
  ```
- **Reproduction / verification:** `_wn15_verify4.py` — a row written with full metadata, then
  `resolver.refresh("youtube","v1", <new url>)`:
  ```
  before refresh: {'stream_url': '.../a.mp3', 'title': 'Real Title', 'artist': 'Real Artist',
                   'cover_url': '.../c.jpg', 'duration': 180.0}
  after  refresh: {'stream_url': '.../b.mp3', 'title': '', 'artist': '', 'cover_url': '', 'duration': 0.0}
  => metadata wiped by cache_stream(): True
  ```
- **Suggested fix:** use `update_cached_stream_url` (`core/database.py:2199`) from `_persist`, which touches
  only `stream_url`/`cached_at`/`expires_at`.
- **Fix side effects:** `update_cached_stream_url` only UPDATEs — it does not INSERT a row that does not exist
  yet, so `_persist` would need to keep the insert path for a first write.
- **Discovered by:** A

---

### 3. Clean areas

- **The "network blip blacklists the provider" bug is absent.** `resolve()` never records a failure of its own:
  the owner's `(None, error)` result only sets `flight.error`; `_mark_failed` is reachable **only** through the
  explicit `mark_unavailable()` API, which no transient-failure path calls. Verified: `_wn15_verify.py` V4 —
  after `resolve(...)` returned `(None, "network down")`, `resolver._failed == {}` and
  `is_unavailable(...) == False`. A dropped connection therefore does not poison the cache.
- **The flight is cleaned up on exceptions.** `resolve()`'s `finally` removes `_inflight[key]` even when
  `resolver_fn` raises; `_wn15_verify.py` V2 shows `_inflight == {}` afterwards. No permanent stall from a
  provider exception.
- **The single-flight itself does deduplicate.** Two concurrent callers for the same `(source, source_id)`
  produced exactly **one** `resolver_fn` invocation (`_wn15_verify.py` V1: `resolver_fn invocations: 1`), and
  `stats()` reports `network_cascades: 1, single_flight_waits: 1` consistently (both counters are updated
  inside the same critical section that decides ownership, L188-207).
- **The in-memory cache is bounded and is a true LRU.** `_mem_set` pops the key before the cap check and evicts
  `next(iter(self._mem))` — the least-recently-used entry — and `_mem_get` re-inserts the entry *with its
  original timestamp*, so a cache hit does not extend the TTL (`_wn15_verify.py`; also pinned by
  `tests/test_cache_lru.py:174-222`). `_failed` is bounded the same way (`_FAIL_MAX_SIZE = 512`).
- **The in-memory TTL is applied to the stored value's write time, not to the read time** —
  `now - entry[1] <= self._mem_ttl` with `entry[1]` set at write time; the LRU touch preserves it.
- **The cache key is `(source, str(source_id))` and nothing else** — there is no quality/parameter dimension in
  the resolver's key. This is safe today because `quality` never varies on a resolution path:
  `AppCore.re_resolve_stream_url_async`'s `quality="high"` parameter is never forwarded to a
  quality-varying call site, and `youtube_service.get_stream_url` defaults to `quality="high"`. **No finding** —
  but a future caller that resolves the same track at a different quality would get the cached high-quality URL.
- **`get_cached_url` never raises.** The DB call is wrapped in `try/except` and logged at debug level
  (L161-162); `_persist` and `invalidate` do the same for their writes (L266-267, L253-254).
- **`_persist` is atomic on the DB side** — `cache_stream` runs inside `with conn:` (`core/database.py:2177`),
  i.e. one transaction, and `get_cached_stream` computes the age from the stored `cached_at`
  (`strftime('%s','now') - strftime('%s', cached_at) < ?`), not from a wall-clock value supplied by the caller.
- **`invalidate()` deliberately keeps downloaded-file rows** — `invalidate_cached_stream` only NULLs
  `stream_url` (`core/database.py:2213-2225`), so `cached_file_path` survives; and it deliberately does *not*
  clear the "unavailable" verdict, which is the documented behaviour and is consistent with `refresh()` clearing
  it (via `_persist` → `self._failed.pop(key, None)`).
- **`same_recording` correctly rejects the classic wrong-version cases**: a remix vs the original, a live vs a
  studio version, a different artist, and a duration off by more than `max(4 s, 2.5 %)`. The extra
  `normalize(title) != normalize(title)` guard for the `remix` version stops "Song (First Remix)" from
  matching "Song (Other Remix)". A track with an **unknown** duration (`0`) skips the duration check
  (by design) but is still protected by the title similarity (≥ 0.88) and the artist match — verified in
  `_wn15_verify.py` V6 ("Song" vs "Totally Different Song" → `False`; "Song"/Artist vs "Song"/Other → `False`).
- **`recover_stream` preserves the playback position** — it normalises `position_ms` (rejects NaN/inf, rounds,
  clamps at 0) and returns it unchanged; the frontend applies it (`ui/web_new_v2/js/player.js:463, 483`).
- **`recover_stream` is bounded and the player is never left hanging.** The 18 s deadline (L121) plus the
  per-phase limits (8/3/4 s) plus the frontend's two-attempt cap
  (`ui/web_new_v2/js/player.js:459-493`) mean there is no retry storm; when the recovery fails the bridge
  returns `{"ok": False, "code": …}` and the frontend calls `stopFailedPlayback()` (L477-492), so playback stops
  with a toast instead of spinning.
- **`recover_stream` never plays an unverified version.** The direct result and the fallback result are both
  checked with `same_recording` when the provider supplies a title (L133, L160), and the SoundCloud→YouTube
  substitution is explicitly refused unless the provider tagged the result `resolved_source == "youtube"`
  (L173-176).
- **A late provider callback cannot corrupt a timed-out `_callback_result`** — `success`/`failure` check
  `completed.is_set()` and return early (verified, `_wn15_verify.py` V8).
- **`core/offline.py` does not report missing files.** `_local_file` checks `os.path.isfile` **and** a minimum
  size (1 byte for a track path, 4096 for a cached stream) and swallows `OSError`; a deleted file is filtered
  out (verified, `_wn15_verify2.py` O6 / `_wn15_verify4.py` O6:
  `available_track -> None`, `available_tracks -> []`). `offline_library` therefore never returns a track
  whose file is gone.
- **`_local_file` correctly refuses to treat a remote URL as a local file** (`urlparse(path).scheme in
  ('http','https')`), which matters because the backend overwrites `track["file_path"]` with a stream URL
  (`core/api.py:1723`); a Windows drive letter (`C:\...`) parses as scheme `c` and is therefore *not* rejected.
- **`is_offline(settings)` reads the live setting, not a stale copy** — `SettingsManager.set` updates the
  in-memory cache synchronously (`core/settings.py:413-418`), and `get` normalises `"true"/"false"` strings.
  Verified (`_wn15_verify3.py`): `True`, `1`, `"true"` → on; `False` → off; the value survives a DB
  round-trip. The string `"1"` is not recognised as on, but the bridge only ever stores a bool
  (`AppApi.set_offline_mode` raises for a non-bool, `core/api.py:4132-4134`), so this is unreachable.

---

### 4. Coverage gaps

- **No live-provider verification.** Everything above was verified with stubbed providers and a temporary
  SQLite database; no YouTube/SoundCloud/Yandex request was made and the real app was never started
  (per the ground rules). The provider-side behaviour of F-1 (how long a real cascade takes when a provider is
  slow) and the reachability of F-2 are therefore inferred from the code's own timeouts
  (`audio/engine.py:208/278`, `core/app.py:449-457`), not measured.
- **`core/proxy.py` was read only where it touches the resolver** (L790–829, L1012–1090, L1304–1334). The
  proxy's own request handling (range requests, credential injection, the `?url=` vs `/api/stream` branches)
  belongs to **WN-11** and was not audited here.
- **`services/*` providers were read only for the units and semantics the WN-15 code depends on**
  (SoundCloud/YouTube duration units, `get_stream_url` callback shape, the executor-based design). Their own
  correctness belongs to **WN-19 / WN-20 / WN-21**.
- **`ui/web_new_v2/js/player.js` was read only for the recovery call contract** (retry cap, resume handling,
  `file_path` stripping at L1703). The player's own state machine belongs to **WN-29**.
- **The `settings` bridge path (`core/api.py::save_setting` → `SettingsManager`) was only sampled.** I verified
  `is_offline` against `SettingsManager` directly, not through the full bridge round-trip.
- **`core/database.py` was read only for the `stream_cache` table and its accessors.** The schema migration
  path, the FTS tables and the write-lock discipline of the rest of the module belong to **WN-12**.
- **The `_inflight` map is never persisted or inspected by the UI**, so there is no runtime visibility into a
  stalled flight; F-2's "permanently stalled" claim is derived from the code path plus the V3 reproduction, not
  from an observed user session.
