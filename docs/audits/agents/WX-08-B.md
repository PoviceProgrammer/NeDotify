## SCENARIO WX-08 — Recommendation loop (taste profile → recommendations → feedback → taste profile) — ROLE B

### 1. Scope reviewed

**Files opened (path: line ranges actually read)**

- `services/taste_profile.py` — 1–634 (whole file: the model, the 60 s memo, the revision scheme, the SQL)
- `services/recommendation_service.py` — 1–917 (whole file: the provider/fan-out + the scoring)
- `core/services/recommendation.py` — 1–240 (whole file: the *other* scoring core)
- `core/api.py` — 455–534 (offline bridge interception), 1100–1169 (`_emit`), 2964–3028
  (`get_personalization`, `get_recommendation_feedback`, `set_recommendation_feedback`,
  `set_artist_alias`, `get_recommendation_quality`, `save_personalization`),
  3030–3160 (`get_storage_info`, `clear_storage`, `_delete_downloaded_files`, `get_wrapped_stats`),
  3280–3460 (`get_home_data`, `get_popular_tracks`, `get_authentic_home_feed`, `get_profile_stats`,
  `_store_artist_binding`), 3461–3514 (`get_artist_profile`), 3530–3619 (`get_recommendations`,
  `get_track_wave`), 3735–3814 (`get_feed`, `get_home_artists`, `get_home_releases`, `get_home_mixes`),
  4090–4129 (`clear_storage_cache`, `get_flow_tracks`)
- `core/database.py` — 95–214 (schema + indexes + thread-local connections), 1054–1113 (`add_track`),
  1289–1328 (`log_listening_history`), 1550–1880 (`add_to_history`, `begin_listening_session`,
  `get_recommendation_quality`, `get_history`, `get_most_played`, `get_top_artists`,
  `get_wrapped_stats`, `get_analytics_summary`), 2036–2085 (`set_setting`, `set_settings_batch`),
  2275–2304 (`get_total_listening_time`), 2405–2489 (`close_thread_connection`, `close`)
- `core/settings.py` — 160–189 (personalization defaults), 340–379 (`get`), 400–519 (`set`, `flush`,
  `_write_batch`), 520–579 (`reset_category`, `reset_all`)
- `utils/cache_manager.py` — 112–278 (`get_storage_details`, `clear_all`, `purge_stream_cache`)
- `services/artist_identity.py` — 1–63 (`name_key`, `artist_aliases`, `canonical_artist`, `track_key`)
- `services/base_service.py` — 1–329 (`_SharedExecutor`, `BaseMusicService`, `_search_cache`,
  `_join_request`)
- `services/lastfm_service.py` — 30–199 (the handlers that receive seed artist/track names)
- `core/app.py` — 215–244 (wiring of `RecommendationService`)
- `main.py` — 95–134 (root logger level = INFO)
- `ui/web_new_v2/js/home.js` — 1–1049 (whole file: `loadHome`, section fan-out, `renderRecommendations`)
- `ui/web_new_v2/js/utils.js` — 1060–1239 (`submitRecommendationFeedback`, context menu)
- `ui/web_new_v2/js/player.js` — 1500–1609 (`requestFlowAutoplay` → `get_flow_tracks`)
- `tests/test_recommendation_service.py` — 1–204; `tests/test_recommendation_signals.py` — 1–107;
  `tests/test_recommendation_bridge.py` — 1–99; `tests/test_taste_profile.py` — 1–175;
  `tests/test_recommendation_ui.py` — 1–140; `tests/test_recommendation_feedback_ui.py` — 1–77
- `.venv_win/Lib/site-packages/webview/util.py` — 225–324 (pywebview bridge dispatch)

**Callees traced into other areas**

- **WN-12** `core/database.py` — `get_history`, `get_wrapped_stats`, `get_analytics_summary`,
  `DatabaseManager._get_connection` / `close_thread_connection` / `close`, the `history` table
  and its indexes. Owning area for the connection-churn and the un-pruned history table.
- **WN-14** `core/settings.py` — `SettingsManager.get/set/flush`, `DEFAULT_SETTINGS["personalization"]`,
  `reset_all` (present, not exposed).
- **WN-18** `services/artist_identity.py` — `artist_aliases` / `track_key` (the alias map that
  `_content_key` rebuilds per call) and `services/track_resolver.py`.
- **WN-21** `services/lastfm_service.py` — `track.getSimilar`, `artist.getTopTracks`,
  `user.getTopArtists` (the third-party disclosure surface).
- **WN-19/20** `services/youtube_service.py`, `services/soundcloud_service.py` —
  `search_sync`, `get_related_tracks_sync`.
- **WN-28/32** `ui/web_new_v2/js/utils.js` (`submitRecommendationFeedback`), `js/home.js`
  (`loadHome`, `renderRecommendations`).
- **WN-29** `ui/web_new_v2/js/player.js` (`requestFlowAutoplay` → `get_flow_tracks`).
- **WN-02** `core/app.py` — construction of the single `RecommendationService`.
- **WN-01** `main.py` — root logger level (INFO) — the reason the taste debug log never reaches disk.

**Cross-component ownership map used in this report**

| Root cause | Owner |
|---|---|
| Per-thread SQLite connections / un-pruned `history` / `get_history` full GROUP BY | WN-12 |
| `_rank_tracks` alias-map rebuild | WN-23 (`services/recommendation_service.py`) + WN-18 (`artist_aliases`) |
| Pending-request key omits the feedback state | WN-23 |
| Provider failure swallowed / error string discarded | WN-23 (swallow) + WN-09/WN-08 (`core/api.py` error path) |
| No "delete my listening history" affordance | WN-08 (`core/api.py::clear_storage`) + WN-12 |
| `core/services/recommendation.py` dead second scoring core | WN-23 |
| `artist_bindings` growth | WN-09 (`core/api.py::_store_artist_binding`) |

---

### 2. Findings

#### F-WX-08-1  [P1] — The 60 s taste-profile memo is per-thread, so every home-page section rebuilds the profile from scratch

- **File:** `services/taste_profile.py:357-371`, `services/taste_profile.py:373-394`,
  `services/taste_profile.py:64`; contributing: `core/database.py:179-201`
- **Confirmed:** yes
- **Description:** `UserTasteProfile` memoises the built profile in a module-level dict for
  `PROFILE_CACHE_TTL = 60.0` s. The memo key is thread-independent (`id(db)` + the alias map),
  but the *revision* that decides whether the memo is still valid embeds the **connection
  object**. `DatabaseManager` hands every thread its own connection
  (`self._local.connection`), so two threads produce two different revisions for the same
  database. The result: a memo written by thread A is never reusable by thread B, and because
  `_cache_put` writes under the *same* key, the two threads overwrite each other's entry.
  The memo therefore only works when the same thread asks twice.
- **Cause:** the revision mixes a per-connection value (`conn`) with per-database values
  (`data_version`, `schema_version`). `PRAGMA data_version` alone already detects commits from
  other connections, and `conn.total_changes` only detects writes on *this* connection; the
  connection identity adds nothing except thread-scoping.
- **Trigger conditions:** any two profile builds on different threads. The home page does
  exactly that: `get_feed`, `get_home_releases` and `get_home_mixes` each build their own
  profile, and they land on different workers of the shared 8-thread pool
  (`services/base_service.py:124`).
- **User impact:** the whole point of the memo ("Recomputing the same profile several times per
  second is pure waste") is lost. A home-page load asks for three separate profiles
  (`get_feed`, `get_home_releases`, `get_home_mixes`), each of which lands on a worker of the
  shared 8-thread pool; when they land on different threads (the normal case) the load
  performs **3 full profile builds instead of 1** — ~20 ms each at 10 000 history rows, plus
  the 1500-row history/favourite/download/playlist materialisation and the `copy.deepcopy`
  of the cached state on every hit.
- **Evidence:**
  ```python
  # services/taste_profile.py:357-371
  @staticmethod
  def _connection_revision(conn) -> Any:
      try:
          data_version = conn.execute('PRAGMA data_version').fetchone()[0]
          schema_version = conn.execute('PRAGMA schema_version').fetchone()[0]
          return (conn, conn.total_changes, data_version, schema_version)   # <-- conn
      except (AttributeError, sqlite3.Error, TypeError):
          return object()
  ```
  ```python
  # core/database.py:179-201
  def _get_connection(self) -> sqlite3.Connection:
      if not hasattr(self._local, "connection") or self._local.connection is None:
          conn = sqlite3.connect(self.db_path, timeout=30.0)
          ...
          self._local.connection = conn
          with self._conns_lock:
              self._all_conns.add(conn)
      return self._local.connection
  ```
  ```python
  # services/taste_profile.py:383-392
  if not isinstance(cache_key, str) and entry['db'] is not db:
      return None
  if entry.get('revision') != revision:      # <-- conn identity mismatch => miss
      return None
  ...
  _profile_cache[cache_key] = {'ts': time.time(), 'db': db, 'revision': revision, 'state': state}
  ```
- **Reproduction / verification:** probe at
  `%TEMP%\opencode\wx08_profile_probe.py` (temp SQLite file, 40 tracks / 40 history rows / 5 favourites):

  ```
  A) SAME THREAD - second build should be a cache hit (0 SELECTs)
     SELECTs on 2nd build in the SAME thread: 0
  B) DIFFERENT THREAD - does the 60s memo survive?
     SELECTs on build in a DIFFERENT thread: 7      <-- full rebuild
  C) ALTERNATING threads (the real home-page fan-out pattern)
     SELECTs per build, one fresh thread each time: [('iter0', 7), ('iter1', 7), ('iter2', 7), ('iter3', 7)]
  ```
  A cache hit issues **zero** SELECTs (that is what
  `tests/test_taste_profile.py:135-146` asserts); 7 SELECTs = the full build path
  (`sqlite_master` + history + favourites + downloads + playlist_tracks + time-habits).
- **Suggested fix:** drop `conn` from the revision tuple and rely on `PRAGMA data_version`
  (cross-connection) plus a per-database monotonically increasing write counter maintained by
  `DatabaseManager` for same-connection writes; or key the memo by `(id(db), id(conn))` so the
  entry is at least reused by the same thread and the cache size bound accounts for it.
- **Fix side effects:** removing `conn` means the revision no longer distinguishes two
  connections to *different* files that happen to share `id(db)` — but `id(db)` already pins
  the `DatabaseManager`, so that cannot happen. `PRAGMA data_version` is only bumped when the
  other connection's transaction commits, so a write that is still open is not observed; that is
  already the current behaviour for cross-thread writes and must be preserved.
- **Discovered by:** B

#### F-WX-08-2  [P1] — `_rank_tracks` rebuilds the artist-alias map ~6 200 times per call; with configured artist bindings it costs 840 ms per call

- **File:** `services/recommendation_service.py:157-159`, `services/recommendation_service.py:243-254`,
  `services/recommendation_service.py:157`; contributing: `services/artist_identity.py:13-32`,
  `services/artist_identity.py:57-63`; growth source: `core/api.py:3461-3475`
- **Confirmed:** yes
- **Description:** `_content_key(track)` calls `track_key(track, artist_aliases(self.settings))`.
  `artist_aliases()` is **not** memoised: it copies `DEFAULT_ALIASES`, re-reads
  `personalization.artist_aliases`, and for every entry of `personalization.artist_bindings`
  computes one or two `sha256` digests and builds a new dict — on **every single call**.
  `_rank_tracks` calls `_content_key` once per known track twice (once to build the `known`
  set at line 243, once in the `known_rows` loop at line 248) plus once per candidate.
  With a realistic library (1 500 favourites + 1 500 downloads + 50 history rows) that is
  **6 180 alias-map rebuilds per `_rank_tracks` call**.
- **Cause:** an expensive, settings-derived value is recomputed inside the innermost loop
  instead of being computed once per request and passed down.
- **Trigger conditions:** any user with a non-trivial library; the cost multiplies by the number
  of configured `artist_bindings`. `artist_bindings` grows **without limit**: every artist
  profile view stores one entry (two when there is no context), see `core/api.py:3461-3475`.
  `get_home_mixes` calls `_rank_tracks` up to 5 times per request
  (`services/recommendation_service.py:694, 697 (via _feed_tracks), 710 (×3 artists), 714`).
- **User impact:** the home page's "Миксы" section takes seconds instead of milliseconds on a
  long-lived library; the flow/wave (`get_flow_tracks`, `player.js:1553`) blocks a bridge thread
  for the same duration, so autoplay picks up late. Measured 840 ms for **one** `_rank_tracks`
  with 50 bindings → up to ~4.2 s for one `get_home_mixes`.
- **Evidence:**
  ```python
  # services/recommendation_service.py:157-159
  def _content_key(self, track):
      # Only remove presentation labels, keeping remixes/live/acoustic versions distinct.
      return track_key(track, artist_aliases(self.settings))
  ```
  ```python
  # services/artist_identity.py:13-32
  def artist_aliases(settings=None):
      aliases = dict(DEFAULT_ALIASES)
      configured = settings.get('personalization', 'artist_aliases', {}) if settings else {}
      ...
      bindings = settings.get('personalization', 'artist_bindings', {}) if settings else {}
      if isinstance(bindings, dict):
          for key, binding in bindings.items():
              ...
              digest = hashlib.sha256(str(refs[source]).encode()).hexdigest()
              lookup = ('@context:' + hashlib.sha256(key.encode()).hexdigest()) if binding.get('context') else name_key(key)
              aliases[lookup] = '@catalog:' + source + ':' + digest
      return aliases
  ```
  ```python
  # services/recommendation_service.py:243, 248-251
  known = {self._content_key(t) for t in self._known_tracks(profile)}
  ...
  for known_track in self._known_tracks(profile):
      if not self._playable(known_track):
          continue
      content = self._content_key(known_track)
  ```
- **Reproduction / verification:** probe at `%TEMP%\opencode\wx08_rank_probe.py` (profile built
  in memory: 1 500 favourites + 1 500 downloads + 50 history rows, 40 candidates):
  ```
  _rank_tracks (1500 fav + 1500 dl + 50 hist): 45.9 ms
  _content_key() calls inside one _rank_tracks: 6180
  _rank_tracks with 50 artist_bindings:        840.6 ms
  _content_key() calls: 6180
  => artist_aliases() rebuilds per _rank_tracks: 6180
  ```
  The same code with 0 bindings takes 45.9 ms; adding 50 `artist_bindings` (which the app writes
  automatically on every artist-profile view) multiplies it by 18.
- **Suggested fix:** compute the alias map once per request (e.g. in `RecommendationService.__init__`
  and refresh it when `personalization.artist_aliases` / `artist_bindings` change), and pass it
  into `track_key`/`canonical_artist` instead of re-deriving it per track. Independently, cap
  `artist_bindings`.
- **Fix side effects:** a cached alias map must be invalidated when the user edits an alias
  (`core/api.py::set_artist_alias`) or when a new binding is stored
  (`core/api.py::_store_artist_binding`); both are on the bridge thread and must bump the
  cached map, otherwise a newly bound artist would not be recognised.
- **Discovered by:** B

#### F-WX-08-3  [P1] — One SQLite connection is leaked per bridge call (pywebview spawns a thread per `js_api` call; the thread-local connection is never closed)

- **File:** `core/database.py:179-201`, `core/database.py:2413-2438`, `core/database.py:2459-2489`;
  contributing: `.venv_win/Lib/site-packages/webview/util.py:305-309`
- **Confirmed:** yes
- **Description:** `DatabaseManager` keeps one `sqlite3.Connection` **per thread**
  (`threading.local`) and pins every connection it ever creates in `self._all_conns`, so the
  handle is never garbage-collected. pywebview executes *every* `js_api` call on a **brand-new
  `Thread`** (`webview/util.py:308`: `thread = Thread(target=_call); thread.start()`). Each such
  thread therefore opens a *new* SQLite connection on first DB access and, when the thread dies,
  the connection survives because `_all_conns` holds a strong reference. Only
  `close_thread_connection()` closes a connection, and no bridge path calls it.
- **Cause:** the thread-local connection model assumes long-lived worker threads, but the bridge
  hands out one-shot threads.
- **Trigger conditions:** every `js_api` call that touches the DB. The home page alone issues
  ~10 (`get_home_data`, `get_playlists`, `get_downloaded_tracks`, `get_popular_tracks`,
  `get_feed`, `get_home_releases`, `get_home_mixes`, `get_home_artists`, `get_wrapped_stats`,
  `fetch_missing_covers`), and `loadHome()` runs on every home-page visit, every 10th track
  change and every feedback change.
- **User impact:** hundreds of open SQLite handles and page caches accumulate for the lifetime
  of the session (each connection carries `PRAGMA cache_size=-8000`, i.e. an 8 MB page-cache
  budget). The handles are only reclaimed at shutdown, which is why `close()` reports
  "could not be closed from the main thread" — the author already observed the symptom
  ("there can be hundreds of these at shutdown").
- **Evidence:**
  ```python
  # .venv_win/Lib/site-packages/webview/util.py:305-309
  if func is not None:
      try:
          func_params = param
          thread = Thread(target=_call)
          thread.start()
  ```
  ```python
  # core/database.py:198-201
              self._local.connection = conn
              with self._conns_lock:
                  self._all_conns.add(conn)
          return self._local.connection
  ```
  ```python
  # core/database.py:2462-2468 (close() docstring — the author saw the symptom)
  A connection created on another thread cannot be used (let alone
  closed) from here - sqlite3 raises ProgrammingError - so those handles
  survive until their own thread ends and are released when their thread
  dies. ... there can be hundreds of these at shutdown
  ```
- **Reproduction / verification:** probe at `%TEMP%\opencode\wx08_conn_probe.py` — 40 simulated
  bridge calls, each on its own thread (exactly what pywebview does):
  ```
  connections before: 1
  connections after 40 simulated bridge calls: 41
  ```
  and at shutdown the manager itself printed
  `40 database connection(s) could not be closed from the main thread (created on another thread)`.
- **Suggested fix:** close the calling thread's connection at the end of every bridge call (a
  `try/finally` in the `AppApi` dispatcher or a decorator on the bridge surface), or stop
  pinning dead threads' connections in `_all_conns` (use a `WeakSet`, or drop the reference when
  the thread-local slot is collected).
- **Fix side effects:** closing the connection at the end of a bridge call means the SQLite page
  cache for that thread is discarded, so a sequence of bridge calls that each need the DB pays
  a fresh connection open each time. A shared, explicitly-managed pool of connections (or a
  single connection with a lock) would be the better end state. `close_thread_connection()`
  must not be called while a transaction is open on that connection.
- **Discovered by:** B

#### F-WX-08-4  [P2] — The home page runs ~55 ms of full-history aggregates on the bridge thread on every load

- **File:** `core/database.py:1599-1624`, `core/database.py:1723-1834`,
  `core/database.py:1836-1860`; callers: `core/api.py:3293-3313`, `core/api.py:3740-3752`,
  `core/api.py:3782-3794`, `core/api.py:3156-3171`
- **Confirmed:** yes
- **Description:** `get_home_data`, `get_feed`, `get_home_mixes` and `get_wrapped_stats` each
  execute a query that aggregates over the **whole** `history` table:
  `get_history()` does `GROUP BY t.id` over every history row (no index can help — it aggregates
  over all rows per track), and `get_wrapped_stats()` runs **four** such scans (totals, top
  tracks, top artists grouped by `LOWER(t.artist)`, activity by weekday). The `history` table
  has one row per playback start and is never pruned.
- **Cause:** the "recent N rows" API is implemented as "aggregate the whole table, then
  `LIMIT`", and there is no time-bounded index or pre-aggregated rollup.
- **Trigger conditions:** a long-lived library. `history` has no upper bound: nothing in the
  repository ever deletes a row from it.
- **User impact:** ~55 ms of synchronous DB work per home-page load at 10 000 history rows, of
  which `get_wrapped_stats` alone is 28 ms. pywebview gives each call its own thread, so the
  WebView is not frozen — but the calls serialise behind each other, each pinning a leaked
  connection (F-WX-08-3), and on a slower disk the wrapped-stats query dominates the home load.
- **Evidence:**
  ```sql
  -- core/database.py:1607-1623
  SELECT t.id AS track_id, MAX(h.played_at) AS played_at, COUNT(*) AS play_count,
         COALESCE(SUM(h.duration_listened), 0) AS duration_listened,
         t.title, t.artist, t.album, t.cover_path, t.cover_url, t.source, t.source_id
  FROM history h JOIN tracks t ON h.track_id = t.id
  GROUP BY t.id
  ORDER BY played_at DESC
  LIMIT ?
  ```
  ```python
  # core/api.py:3293-3313 — all synchronous on the bridge thread
  def get_home_data(self):
      history = self._core.db.get_history(limit=10) or []
      ...
      total_time_ms = self._core.db.get_total_listening_time() or 0
      top_tracks = self._core.db.get_most_played(limit=10) or []
      top_artists = self._core.db.get_top_artists(limit=10) or []
      ...
      "playlists": self.get_playlists(),
  ```
- **Reproduction / verification:** probe at `%TEMP%\opencode\wx08_conn_probe.py`, 10 000 history
  rows / 500 tracks:
  ```
  db.get_history(limit=10)   [get_home_data]              3.76 ms
  db.get_history(limit=30)   [get_feed/get_home_mixes]    3.80 ms
  db.get_most_played(10)     [get_home_data]              0.13 ms
  db.get_top_artists(10)     [get_home_data]              0.25 ms
  db.get_total_listening_time() [get_home_data]           0.02 ms
  db.get_wrapped_stats('week')  [get_wrapped_stats]      28.01 ms
  db.get_wrapped_stats('all')                            17.99 ms
  db.get_analytics_summary()                              1.02 ms
  TOTAL bridge-thread DB time per home load              54.98 ms
  ```
- **Suggested fix:** add a `history(track_id, played_at)`-style covering index and rewrite
  `get_history` as a windowed query over the newest N history rows (`ROW_NUMBER() OVER
  (PARTITION BY track_id ORDER BY played_at DESC)`) so the cost is `O(N)` not `O(history)`;
  pre-aggregate `get_wrapped_stats` into a daily rollup table; and move the home-page queries
  off the bridge thread (the bridge methods already return via `_emit` for the feed sections —
  `get_home_data` and `get_wrapped_stats` do not).
- **Fix side effects:** a windowed `get_history` changes the semantics of `duration_listened`
  (currently the sum over *all* plays of a track, not just the newest) — the profile and the
  "recently played" card rely on the current behaviour, so the two must be split explicitly.
  A rollup table needs a migration and a backfill.
- **Discovered by:** B (root cause of the un-pruned table: WN-12)

#### F-WX-08-5  [P2] — A provider failure is indistinguishable from "you have no recommendations"; the error string is discarded and the section is hidden

- **File:** `core/api.py:3744-3748`, `core/api.py:3774-3776`, `core/api.py:3787-3789`;
  `services/recommendation_service.py:396-400`, `services/recommendation_service.py:471-476`;
  `ui/web_new_v2/js/home.js:275-280`; pinned by `tests/test_recommendation_ui.py:73`
- **Confirmed:** yes
- **Description:** there is no "recommendations unavailable" state anywhere in the loop.
  (a) In the bridge, the provider error is thrown away: `error_callback=lambda _error:
  self._emit("feed_ready", [])` — the message never reaches the UI, and `feed_ready` with an
  empty list is indistinguishable from "no recommendations".
  (b) In the service, a per-provider exception is swallowed at DEBUG
  (`logger.debug('Recommendation provider unavailable: %s', exc); continue`) and the section
  is filled with `familiar` — the user's own favourites, downloads and recent history — which
  is rendered under the heading "Рекомендации" exactly like real discoveries.
  (c) In the UI, an empty feed *hides* the section outright
  (`sec.style.display = (tracks && tracks.length > 0) ? 'block' : 'none'`), so the error case
  and the "no data yet" case look the same: nothing at all.
- **Cause:** the error channel terminates at the bridge boundary (the error payload is dropped),
  and the fallback content is drawn from the same code path as the success content.
- **Trigger conditions:** any provider outage, DNS failure, proxy failure or API-key problem;
  also the case where the profile build itself throws (`build_from_db` catches everything and
  returns a partially-filled profile — `services/taste_profile.py:328-331`).
- **User impact:** the user is told nothing. They cannot tell "the app has nothing to suggest"
  from "the app failed to fetch suggestions", and they may conclude their library is empty.
  The `home.js` 20 s watchdog only produces a "Повторить" button for a *hang*; a *failure*
  produces silence.
- **Evidence:**
  ```python
  # core/api.py:3744-3748
  self._core.recommendations.get_feed(
      history, max_results=max_results,
      callback=lambda tracks: self._emit("feed_ready", (tracks or [])[:max_results]),
      error_callback=lambda _error: self._emit("feed_ready", []),   # <-- error dropped
  )
  ```
  ```python
  # services/recommendation_service.py:396-400
              try:
                  items = future.result() or []
              except Exception as exc:
                  self.logger.debug('Recommendation provider unavailable: %s', exc)
                  continue
  ```
  ```python
  # services/recommendation_service.py:471-476
  familiar = profile.get_seed_tracks(limit=20) + profile.get_local_liked_and_downloaded_tracks(limit=20) + profile.recent_history
  tracks = self._rank_tracks(candidates + familiar, profile, max_results,
                             exclude_tracks=profile.recent_history[:1])
  if not tracks and profile.is_empty() and not profile.recent_history:
      tracks = self._rank_tracks(CURATED_WELCOME_TRACKS, profile, max_results)
  ```
  ```js
  // ui/web_new_v2/js/home.js:275-280
  export function renderRecommendations(tracks) {
      clearFeedTimeout('home-recommended');
      const sec = document.getElementById('home-recommended-section');
      if (sec) sec.style.display = (tracks && tracks.length > 0) ? 'block' : 'none';
      renderFeedSection('home-recommended', tracks);
  }
  ```
- **Reproduction / verification:** `tests/test_recommendation_bridge.py:26-34` pins the current
  behaviour — `error_callback("provider unavailable")` must produce exactly `("feed_ready", [])`;
  `tests/test_recommendation_ui.py:73` pins that an empty feed sets
  `home-recommended-section.style.display === 'none'`. Both pass today
  (`56 passed` for the six recommendation test files). The failing-provider path can be
  reproduced live by disconnecting the network and opening the home page: the "Рекомендации"
  section either disappears or shows the user's own library tracks, with no message.
- **Suggested fix:** carry the error to the UI (e.g. `feed_ready` with `{tracks: [], status:
  'unavailable', error: ...}`), render an explicit "Рекомендации недоступны — повторить" state
  distinct from the empty state, and separate the "familiar" fallback from the discovery list
  so the section can label them.
- **Fix side effects:** changing the `feed_ready` payload shape breaks
  `tests/test_recommendation_bridge.py:26-34` and `tests/test_recommendation_ui.py:80-94` and
  the `events.js` dispatcher; the payload contract must be changed in both places at once.
  `core/api.py` has a matching offline-interception branch
  (`core/api.py:464-466`) that emits the same empty payload and must be kept consistent.
- **Discovered by:** B

#### F-WX-08-6  [P2] — The pending-request key omits the feedback state, so a "Не интересно" issued while a feed is in flight is answered with the pre-feedback feed

- **File:** `services/recommendation_service.py:626-630`, `services/recommendation_service.py:691-717`,
  `services/recommendation_service.py:481-493`; `services/base_service.py:140-161`;
  `ui/web_new_v2/js/home.js:9`
- **Confirmed:** yes (the key omits the feedback state — verified by reading the code); the
  user-visible window is a race whose probability depends on provider latency
- **Description:** `get_feed`/`get_mixes`/`get_releases` de-duplicate concurrent identical
  requests through `BaseMusicService._join_request`, keyed by
  `'recommendation:pending-feed:' + repr((history, personalization, max_results))`.
  `personalization` is always `None` (the bridge never passes it) and the feedback state is
  not part of the key. When a request is already pending, the new caller **joins** it and
  receives the leader's result. The feedback *cache* key inside `_feed_tracks` does include
  `repr(self._feedback())` (line 463) — but that key is computed when the leader's task
  *starts*. If the user applies "Не интересно" while the leader is already inside
  `_collect_candidates` (up to a 12 s provider fan-out), the leader publishes the feed it
  computed *before* the feedback was applied, and the freshly triggered `loadHome()`
  (`ui/web_new_v2/js/home.js:9` → `loadHome()`) renders that stale list.
- **Cause:** the pending-request de-duplication key is built from the *request parameters*
  only, while the *result* depends on additional mutable state (the negative feedback and the
  taste profile) that the key does not capture.
- **Trigger conditions:** the user clicks "Не интересно"/"Не рекомендовать артиста" in the
  context menu while a feed request is still running. `loadHome()` re-requests all four
  sections 75 ms apart, so the window is the whole provider fan-out duration (up to 12 s).
- **User impact:** the blocked track/artist is still shown in the refreshed feed; the user's
  explicit negative feedback appears to have been ignored. The *next* refresh (e.g. the next
  track change) recomputes correctly, so the behaviour is intermittent — the worst kind.
- **Evidence:**
  ```python
  # services/recommendation_service.py:626-630
  def get_feed(self, history=None, personalization=None, max_results=20, callback=None, error_callback=None):
      max_results = max(0, min(50, int(max_results)))
      key = 'recommendation:pending-feed:' + repr((history, personalization, max_results))
      return self._async_recommendation(key, lambda: self._feed_tracks(self._profile(history), max_results),
                                        callback, error_callback)
  ```
  ```python
  # services/recommendation_service.py:461-466 — the feed cache key DOES carry the feedback
  signature = (..., repr(self._feedback()), repr(artist_aliases(self.settings)),
               repr(self.settings.get('personalization', 'favorite_genres', []) ...),
               self.settings.get('personalization', 'discovery_ratio', .2) ...)
  key = 'recommendation:feed:' + hashlib.sha256(repr(signature).encode('utf-8')).hexdigest()
  ```
  ```python
  # services/base_service.py:140-147 — the join swallows the second request
  def _join_request(self, key, callback, error_callback):
      with self._cache_lock:
          listeners = self._pending_requests.get(key)
          if listeners is not None:
              listeners.append((callback, error_callback))
              return False, None, None
  ```
- **Reproduction / verification:** start a feed request, apply `set_recommendation_feedback`
  while `_collect_candidates` is in flight (the provider fan-out takes up to 12 s), then
  observe the `feed_ready` payload: it still contains the blocked track. A deterministic
  version: patch `RecommendationService._collect_candidates` to block on an `Event`, call
  `get_feed(...)`, then flip `settings['personalization']['blocked_artists']` and call
  `get_feed(...)` again — the second call joins the first and returns the unblocked result.
  **Not yet executed** (needs a controlled provider stub); the key omission itself is
  confirmed by reading the code.
- **Suggested fix:** include the feedback fingerprint in the pending-request key (the same
  `repr(self._feedback())` already used for the feed cache key), and/or make
  `_join_request` reject a join when the leader's result predates the current feedback
  revision.
- **Fix side effects:** including the feedback in the pending key means two home sections
  requested in the same tick with different feedback state no longer share one fan-out —
  slightly more provider traffic in the rare case, but each section gets a correct result.
  The `repr(...)` key is already multi-kilobyte for a 30-row history; a cheaper
  hash-based key would be an improvement in its own right.
- **Discovered by:** B

#### F-WX-08-7  [P2] — "Clear storage" touches no database table: the listening history, the favourites and the negative feedback cannot be erased from the app

- **File:** `core/api.py:3105-3136`, `core/api.py:3138-3154`, `core/api.py:4097-4108`;
  `utils/cache_manager.py:137-156`; `core/settings.py:537-549`
- **Confirmed:** yes
- **Description:** the taste profile is *the user's complete listening history*. None of the
  storage-clearing paths touch it:
  - `clear_storage("cache")` → `CacheManager.clear_all()` → `clear_covers_cache()`,
    `clear_streams_cache()`, `clear_temp()` → **deletes files only, zero SQL**.
  - `clear_storage("all")` → the same plus `_delete_downloaded_files()`, which `os.remove()`s
    each downloaded file — **still zero SQL**, so the `tracks` rows keep `is_downloaded = 1`
    and the now-dead `file_path`, and the history/favourite rows are untouched.
  - `clear_storage_cache()` — the bridge method the UI actually calls
    (`ui/web_new_v2/js/settings.js:231-232`) — is `clear_all()` only.
  - `SettingsManager.reset_all()` exists (`core/settings.py:546-549`) and *would* reset
    `personalization.blocked_artists` / `disliked_tracks` / `artist_aliases` to their defaults
    (`core/settings.py:166-176`), but it is **not exposed through the bridge** and has no UI
    control; `reset_category` is only used by tests.
  - There is **no** code path anywhere that deletes from `history`, `tracks`,
    `playlist_tracks` or `listening_stats`.
- **Cause:** "storage" was defined as *cache bytes*, not as *user data*; the data-governance
  affordance was never specified.
- **Trigger conditions:** any user who wants the app to stop remembering what they listen to,
  or who wants their listening history gone before selling the machine.
- **User impact:** the user's complete listening history — every track they played, with
  timestamps — is permanent and unerasable from the UI. It survives "clear cache", survives
  "clear all", and survives deleting the downloaded files. The only way to remove it is to
  delete `~/.nedotify/nedotify_storage.db` by hand, which the project's own rules forbid
  ("`~/.nedotify/` is the user's library. Clearing it is not a cleanup step.").
- **Evidence:**
  ```python
  # core/api.py:3120-3136  (the whole method)
  storage_type = str(storage_type or "cache").strip().lower()
  if storage_type not in ("cache", "all"):
      logger.warning("clear_storage: unsupported storage_type %r", storage_type)
      return False
  cache = getattr(self._core, "cache", None)
  if cache is None:
      logger.error("clear_storage: cache manager unavailable")
      return False
  cache.clear_all()
  if storage_type == "all":
      removed = self._delete_downloaded_files()
      logger.info("clear_storage: removed %d downloaded file(s)", removed)
  return True
  ```
  ```python
  # utils/cache_manager.py:152-156  (no SQL anywhere)
  def clear_all(self):
      """Clear all caches safely."""
      self.clear_covers_cache()
      self.clear_streams_cache()
      self.clear_temp()
  ```
  ```python
  # core/api.py:3138-3154  (files only; the DB keeps is_downloaded = 1 and the stale path)
  def _delete_downloaded_files(self) -> int:
      removed = 0
      tracks = self._core.db.get_downloaded_tracks() or []
      for t in tracks:
          ...
          if os.path.isfile(fp):
              os.remove(fp)
              removed += 1
      return removed
  ```
  ```python
  # core/settings.py:546-549  (present, but no bridge method and no UI control)
  def reset_all(self):
      """Reset all settings to defaults."""
      for category in DEFAULT_SETTINGS:
          self.reset_category(category)
  ```
- **Reproduction / verification:** probe at `%TEMP%\opencode\wx08_conn_probe.py` prints
  `CacheManager.clear_all`'s source: three directory-clearing calls, no SQL. A DB-level check:
  after `clear_storage("all")`,
  `SELECT COUNT(*) FROM history` is unchanged and
  `SELECT id, is_downloaded, file_path FROM tracks WHERE is_downloaded = 1` still lists the
  tracks whose files were just deleted.
- **Suggested fix:** add an explicit, separately-confirmed data-erase action (e.g.
  `clear_storage("history")` or a dedicated `erase_listening_data()`) that runs the required
  SQL — `DELETE FROM history`, `DELETE FROM listening_stats`, and either `DELETE FROM tracks`
  or a reset of the favourite/download flags — and a "reset personalisation" action that calls
  `settings.reset_category("personalization")`. Both must be confirmed by the user, because
  `~/.nedotify/` is the user's library. `clear_storage("all")` must also clear
  `tracks.is_downloaded` / `tracks.file_path` for the files it removed, or the DB will keep
  claiming files that no longer exist.
- **Fix side effects:** `ON DELETE CASCADE` from `tracks` to `history` means deleting a track
  row also deletes its history rows, and `playlist_tracks` cascades too — the exact hazard the
  dup-cleanup migration was rewritten to avoid (`core/database.py:385-392`). The erase action
  must be explicit about what it removes.
- **Discovered by:** B (owning area for the DB side: WN-12; for the bridge surface: WN-08)

#### F-WX-08-8  [P2] — The negative-feedback lists are capped in one write path and not in the other; the cap silently forgets the oldest "never show me again" entries

- **File:** `core/api.py:2979-3000`, `core/api.py:3024-3028`,
  `services/recommendation_service.py:151-155`
- **Confirmed:** yes
- **Description:** `set_recommendation_feedback` truncates with `values[-1000:]` (keeping the
  **newest** 1000 entries). `save_personalization` writes the *same* two keys
  (`personalization.blocked_artists`, `personalization.disliked_tracks`) with **no cap at
  all** — it is a public bridge method, so the cap is not a property of the data, only of one
  caller. Reading is also unbounded: `_feedback()` builds two sets from the whole list on
  every call, and it is called from five sites
  (`_seed_tracks`, `_collect_candidates`, `_rank_tracks`, `_feed_tracks`'s signature, and
  `_get_merged_seed_artists`).
- **Cause:** the size limit lives in the caller rather than in the store, so it is bypassable
  and inconsistent; the truncation direction (`[-1000:]`) silently drops the oldest entries
  rather than refusing new ones.
- **Trigger conditions:** more than 1000 distinct blocked artists or disliked tracks — a
  heavy listener over a long life. The cap is reached silently.
- **User impact:** (a) the oldest "не рекомендовать" entries silently stop being honoured and
  those artists/tracks reappear in recommendations — the opposite of what the user asked for;
  (b) with a full 1000+1000 list, each `_feedback()` call costs ~4.2 ms and it is called 5+
  times per request; (c) `save_personalization` can write an arbitrarily large JSON blob into
  a single `settings` row.
- **Evidence:**
  ```python
  # core/api.py:2999  (the cap)
              self._core.settings.set('personalization', key, values[-1000:])
  ```
  ```python
  # core/api.py:3024-3028  (the same keys, no cap)
  def save_personalization(self, data: dict):
      if isinstance(data, dict):
          for k, v in data.items():
              self._core.settings.set("personalization", k, v)
      return True
  ```
  ```python
  # services/recommendation_service.py:151-155
  def _feedback(self):
      artists = self.settings.get('personalization', 'blocked_artists', []) if self.settings else []
      tracks = self.settings.get('personalization', 'disliked_tracks', []) if self.settings else []
      return ({self._artist_key(a) for a in artists if isinstance(a, str)} if isinstance(artists, list) else set(),
              {self._content_key(t) for t in tracks if isinstance(t, dict)} if isinstance(tracks, list) else set())
  ```
- **Reproduction / verification:** probe at `%TEMP%\opencode\wx08_rank_probe.py`:
  ```
  _feedback() with 1000 blocked + 1000 disliked: 4.24 ms per call
  '_feedback()' call sites in RecommendationService: 5
  ```
  Cap behaviour: call `api.set_recommendation_feedback(track, 'artist')` 1001 times with
  distinct artists and assert `len(settings.get('personalization','blocked_artists')) == 1000`
  and that the *first* artist is gone while the last is present.
  `save_personalization` is not called from the shipped UI (grep of `ui/web_new_v2` finds no
  caller), so the unbounded path is currently reachable only from the bridge surface.
- **Suggested fix:** move the bound into the store (`SettingsManager` or a dedicated
  `FeedbackStore`) so every write path is bounded, reject new entries beyond the bound instead
  of dropping the oldest, and cap `save_personalization` for these two keys.
- **Fix side effects:** changing "drop the oldest" to "reject the newest" changes the
  user-visible behaviour for a user who is already at the cap; the toast in
  `ui/web_new_v2/js/utils.js:1095-1096` would need a third message.
- **Discovered by:** B

#### F-WX-08-9  [P2] — The `history` table grows without bound and is never pruned; three of the loop's entry points aggregate over all of it

- **File:** `core/database.py:272-287` (schema + indexes), `core/database.py:1599-1624`
  (`get_history`), `core/database.py:1723-1834` (`get_wrapped_stats`), `core/database.py:1836-1860`
  (`get_analytics_summary`)
- **Confirmed:** yes
- **Description:** `history` gets one row per playback start
  (`core/database.py:1558-1567`, `1296-1318`) and nothing ever removes one — there is no
  `DELETE FROM history` anywhere in the repository (verified by grep over the whole tree).
  The two indexes that exist (`idx_history_played_at`, `idx_history_track_id`) do not help the
  aggregate queries the loop actually runs: `get_history` groups by track over the whole table
  and only then applies `LIMIT`; `get_wrapped_stats` runs four full aggregates (one of them
  `GROUP BY LOWER(t.artist)`, which has no index at all).
- **Cause:** no retention policy and no rollup; the "last N" queries are written as
  "aggregate everything, then LIMIT".
- **Trigger conditions:** the table grows linearly with the number of plays. At ~50 plays a
  day a heavy listener reaches 10 000 rows in ~7 months.
- **User impact:** the home page's DB cost grows without bound (measured 55 ms per load at
  10 000 rows, and roughly linearly beyond), the SQLite file grows, and the Wrapped stats
  query becomes the slowest thing on the home page.
- **Evidence:**
  ```sql
  -- core/database.py:274-287
  CREATE TABLE IF NOT EXISTS history (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      track_id INTEGER NOT NULL,
      played_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
      duration_listened REAL DEFAULT 0,
      completed INTEGER DEFAULT 0,
      FOREIGN KEY (track_id) REFERENCES tracks(id) ON DELETE CASCADE
  );
  CREATE INDEX IF NOT EXISTS idx_history_played_at ON history(played_at);
  CREATE INDEX IF NOT EXISTS idx_history_track_id ON history(track_id);
  ```
  ```sql
  -- core/database.py:1772-1787 (get_wrapped_stats, top artists)
  SELECT t.artist, COUNT(h.id) as plays, COALESCE(SUM(CASE ...), 0) as total_listened_sec
  FROM history h JOIN tracks t ON h.track_id = t.id
  WHERE h.played_at >= datetime('now', '-7 days')
  AND t.artist IS NOT NULL AND t.artist != '' AND t.artist != 'Unknown Artist'
  GROUP BY LOWER(t.artist)
  ORDER BY plays DESC, total_listened_sec DESC
  LIMIT 5
  ```
- **Reproduction / verification:** probe at `%TEMP%\opencode\wx08_conn_probe.py`:
  ```
  history rows: 10000
  rows are never deleted (no DELETE FROM history anywhere in the repo)
  db.get_wrapped_stats('week'): 28.01 ms
  db.get_history(limit=10): 3.76 ms
  ```
  To see the growth, insert N rows and re-measure: the cost is linear in N.
- **Suggested fix:** add a retention policy for `history` (e.g. keep 12 months, or keep the
  newest 50 000 rows) plus a daily rollup table that the Wrapped queries read; rewrite
  `get_history` as a windowed query over the newest N rows.
- **Fix side effects:** pruning removes data the Wrapped "all time" statistics and
  `get_recommendation_quality` read; the rollup must be able to answer those questions
  before the raw rows are dropped. The taste profile reads at most the newest
  `HISTORY_LIMIT = 1500` rows, so pruning below that floor is invisible to the recommender.
- **Discovered by:** B (owning area: WN-12)

#### F-WX-08-10  [P3] — `core/services/recommendation.py` is a dead second scoring core with a different algorithm, fabricated inputs and non-deterministic output

- **File:** `core/services/recommendation.py:1-240` (whole file)
- **Confirmed:** yes
- **Description:** the file the repository map describes as "recommendation scoring core" is
  imported by nothing (grep over the whole tree finds no importer of
  `core.services.recommendation`, `RecommendationEngine` or `build_real_engine`). The live
  scoring lives entirely inside `RecommendationService` (`_calculate_taste_weights`,
  `_rank_tracks`, `_seed_tracks`). The dead module implements a *different* algorithm —
  Euclidean distance over `bpm`/`energy`/`mood`/`acoustics`/`bass` — on a
  `user_profile`/`catalog` shape that nothing produces. The `tracks` table has **no** such
  columns, so `build_real_engine` fabricates them for every row; the mixes ratio is drawn
  with `random.uniform` / `random.sample`, so the output is not reproducible; and
  `generate_artist_spotlights()` returns hard-coded fake artists
  (`"Similar Artist"`, `"a_niche"`).
- **Cause:** an earlier design put the scoring core in `core/`; the implementation moved into
  `services/recommendation_service.py` and the old file was never removed.
- **Trigger conditions:** always — the file is simply present and misleading.
- **User impact:** none today (nothing calls it). The risk is maintenance: it is a second,
  contradictory definition of "the user's taste" living next to the real one, and it is the
  file a reader would naturally open to understand the recommendation algorithm.
- **Evidence:**
  ```python
  # core/services/recommendation.py:60-61
          familiar_count = int(count * random.uniform(0.6, 0.7))
          discovery_count = count - familiar_count
  ```
  ```python
  # core/services/recommendation.py:232-238
      for t in catalog:
          t["id"] = str(t.get("id", ""))
          t["bpm"] = t.get("bpm") or 120
          t["energy"] = t.get("energy") or 0.5
          t["mood"] = t.get("mood") or 0.5
          t["acoustics"] = t.get("acoustics") or 0.5
          t["bass"] = t.get("bass") or 0.5
  ```
  ```python
  # core/services/recommendation.py:160-176
  def generate_artist_spotlights(self) -> Dict[str, List[Dict[str, Any]]]:
      return {
          "similar_artists": [
              {"artist_id": "a_sim", "artist_name": "Similar Artist", "reason": "Based on your tastes"},
          ],
          ...
      }
  ```
  The `tracks` schema (`core/database.py:213-239`) contains no `bpm`/`energy`/`mood`/
  `acoustics`/`bass` column.
- **Reproduction / verification:** `grep -rn "build_real_engine\|RecommendationEngine\|core\.services\.recommendation"` over the repo root returns only the definitions themselves plus one unrelated
  User-Agent string in `services/lastfm_service.py:157`.
- **Suggested fix:** delete the file, or replace it with a genuine, pure, testable scoring
  core extracted from `RecommendationService` (see ARCH-1).
- **Fix side effects:** none — nothing imports it. `docs/audits/WIN_AUDIT_CONTEXT.md` lists it
  as "recommendation scoring core" and would need updating.
- **Discovered by:** B

#### F-WX-08-11  [P3] — `AppApi.get_recommendations` blocks its bridge thread for up to 3 s and is unreachable from the shipped UI

- **File:** `core/api.py:3537-3553`, `core/api.py:492`
- **Confirmed:** yes
- **Description:** `get_recommendations` is the scenario's named entry point
  (`core/api.py::get_recommendations`), but no JavaScript in `ui/web_new_v2` calls it (grep
  for `get_recommendations` across the whole `ui/` tree returns nothing; only
  `get_flow_tracks` is called, from `js/player.js:1553`). The method also blocks its calling
  thread on an `Event` with a 3 s timeout while the provider fan-out runs — and the fan-out
  itself has a 12 s deadline (`services/recommendation_service.py:367`), so the method
  routinely returns an empty list after 3 s while the provider work continues in the
  background, unobserved.
- **Cause:** a synchronous bridge method was kept from an earlier design and never removed or
  wired up.
- **Trigger conditions:** any caller of the bridge method (currently none from the UI).
- **User impact:** none today; the risk is that the 3 s blocking wait is copied by a future
  caller, and that the offline branch (`core/api.py:492`) keeps a dead method alive.
- **Evidence:**
  ```python
  # core/api.py:3537-3553
  def get_recommendations(self, track_data: dict, max_results: int = 10):
      """Get recommended tracks for seed track synchronously with timeout."""
      res = []
      evt = threading.Event()
      def callback(tracks):
          if tracks:
              res.extend(tracks)
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
- **Reproduction / verification:** `grep -rn "get_recommendations" ui/` → no matches;
  `grep -rn "get_recommendations" tests/` → only
  `tests/test_recommendation_bridge.py:8-18`, which drives the method directly and therefore
  pins a method the app never uses.
- **Suggested fix:** delete the method (and its offline branch), or replace it with the
  event-based `get_track_wave` pattern that the UI actually uses.
- **Fix side effects:** `tests/test_recommendation_bridge.py:8-18` would need to be removed or
  retargeted.
- **Discovered by:** B

#### F-WX-08-12  [P2] — The shared 4-worker provider pool starves the second concurrent home-page fan-out, which is then silently reported as "no recommendations"

- **File:** `services/recommendation_service.py:57`, `services/recommendation_service.py:366-391`,
  `services/recommendation_service.py:451-479`; `ui/web_new_v2/js/home.js:176-193`
- **Confirmed:** hypothesis — the mechanism is confirmed by reading the code; the *magnitude*
  depends on real provider latency, which was not measured here
- **Description:** the home page fires four feed sections 75 ms apart. `get_feed` and
  `get_home_mixes` share one fan-out (same candidate key → the `_candidate_flights` single-flight
  in `_collect_candidates`), but `get_home_releases` starts a **second** fan-out with a
  different key (`seeds=[]`). Both fan-outs submit their jobs to the same
  `ThreadPoolExecutor(max_workers=4)` and both then wait at most
  `min(8.0, deadline - now)` seconds. With two fan-outs × up to 11 jobs each on 4 workers, the
  later fan-out's jobs can still be queued when its 8 s wait expires; the pending futures are
  cancelled and the section ends up with no candidates at all.
- **Cause:** a shared, small provider pool with a fixed wall-clock budget that does not
  account for the queue time of the jobs it just submitted.
- **Trigger conditions:** a slow provider (YouTube/SoundCloud/Last.fm latency) plus two
  concurrent fan-outs — i.e. exactly a home-page load on a slow network.
- **User impact:** the "Релизы" (and possibly "Рекомендации") section is empty or thin while the
  app reports success. Because of F-WX-08-5 the user is not told anything.
- **Evidence:**
  ```python
  # services/recommendation_service.py:57
  self._candidate_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix='RecommendationMetadata')
  ```
  ```python
  # services/recommendation_service.py:366-391
  def _collect_uncached_candidates(self, seeds, artists, limit):
      deadline = time.monotonic() + 12.0
      ...
      futures = [self._candidate_executor.submit(work) for _, _, work in jobs]
      done, pending = wait(futures, timeout=min(8.0, max(0, deadline - time.monotonic()))) if futures else (set(), set())
      for future in pending:
          future.cancel()
  ```
  ```js
  // ui/web_new_v2/js/home.js:182-187
  requestHomeSection('home-recommended', 'get_feed', [10]);
  await delay(75);
  requestHomeSection('home-releases', 'get_home_releases', [10]);
  await delay(75);
  requestHomeSection('home-mixes', 'get_home_mixes', [10]);
  ```
- **Reproduction / verification:** **not executed** — this needs a live or stubbed provider
  with controllable latency. What is missing: a measurement of how long the
  `get_home_releases` fan-out's jobs actually wait in the queue relative to the 8 s budget.
  A deterministic reproduction would patch `youtube_service.search_sync` with a 3 s sleep and
  count the candidates returned by `get_releases` while `get_feed` is also running.
- **Suggested fix:** give each fan-out its own budget that starts when its jobs *start*
  (or raise the worker count / use per-section executors), and report "candidates unavailable"
  when the wait expires with jobs still queued, so F-WX-08-5 can surface it.
- **Fix side effects:** more workers means more concurrent outbound provider requests
  (YouTube/SoundCloud rate limits) and more sockets; the 4-worker bound is probably a
  deliberate politeness limit.
- **Discovered by:** B

---

### 3. Clean areas

- **The dependency direction in the live path is clean — there is no cycle.**
  `core/api.py` → `core/app.py` → `services/recommendation_service.py` →
  `services/taste_profile.py` / `services/artist_identity.py` / `services/track_resolver.py` /
  `services/lastfm_service.py`. `services/taste_profile.py` and
  `services/recommendation_service.py` import **nothing** from `core/` (the three
  `services/ → core/` imports in the tree are in `lyrics_lookup.py`,
  `soundcloud_service.py` and `smart_playlists.py`, none of them on this path).
  `core/services/recommendation.py` imports only the stdlib.
- **The profile cache's invalidation semantics are correct where they are exercised.**
  A new listen does change the recommendations: the revision tuple includes
  `conn.total_changes` (same-connection write) and `PRAGMA data_version` (other-connection
  commit), and the entry is only reused when the revision is *identical*. Verified
  experimentally: after a same-thread `begin_listening_session` the next build issued 6
  SELECTs (a rebuild), and after a **cross-thread** `begin_listening_session` (the real
  bridge-thread case) it also issued 6 SELECTs — the cached profile was correctly discarded
  in both cases. (The top-artist *score* does not move at that moment, and that is by design:
  a playback-start row has `duration_listened = 0` with `listening_measured = 1`, which
  `_listening_weight` deliberately scores as `0.0`
  (`services/taste_profile.py:565-566`) until the measured duration is written back.) The
  failure mode of this cache is over-invalidation (F-WX-08-1), never staleness.
- **The negative feedback is applied consistently and is not leaked to providers.**
  `_seed_tracks` and `_get_merged_seed_artists` filter `blocked` artists before any provider
  call, so a blocked artist's name is never sent to YouTube/Last.fm as a search query;
  `_rank_tracks` excludes blocked artists and disliked tracks by content key, including the
  alias and "Official Video" variants. `tests/test_recommendation_signals.py:64-75` pins
  exactly this, including that the *cached* feed is invalidated when the feedback changes
  (the feed cache key contains `repr(self._feedback())`).
- **The privacy footprint is small and the logs are clean.** The derived taste profile
  (top artists, genre distribution, time-of-day habits) exists **only in memory**
  (`services/taste_profile.py::_profile_cache`); it is never persisted, never exported and
  never sent to a provider. The artist/genre names are logged at `DEBUG`
  (`services/taste_profile.py:430-436`) and the root logger is `INFO`
  (`main.py:104-105`), so they never reach `~/.nedotify/logs/app.log`. The `print()` on line
  443 emits counts only.
- **The raw history is never sent to a third party.** The provider fan-out uses at most
  5 seed tracks and 2 artist names (`services/recommendation_service.py:371-387`); the
  history table, the favourites, the downloads, the playlist contents, the blocked-artists
  list and the disliked-tracks list never leave the machine. Last.fm additionally requires the
  user to have configured an API key (`_lastfm_enabled()`), so by default the only external
  disclosure is YouTube/SoundCloud search queries and media ids.
- **The provider fan-out has a proper single-flight.** `_collect_candidates` uses a
  `Future` keyed by the candidate signature
  (`services/recommendation_service.py:336-364`), so `get_feed` and `get_home_mixes` share
  one outbound fan-out instead of two; `tests/test_recommendation_service.py:133-151` pins
  this.
- **The pending-request de-duplication is properly locked.** `_candidate_flights` and
  `_pending_requests` are guarded by the class-level `BaseMusicService._cache_lock` (an
  `RLock`), satisfying the repository's "a new shared field joins its class's existing lock"
  rule.
- **`_emit` never runs on the UI thread.** `core/api.py:1147-1154` hands the
  `evaluate_js` call to a `EmitWorker` thread when the caller is the main thread, and the
  recommendation callbacks all fire from worker threads.
- **The recommendation provenance survives the round-trip.** `recommendation_origin` is set
  on every feed item (`services/recommendation_service.py:476`) and is recorded into
  `history.recommendation_context` (`core/api.py:1325`,
  `core/database.py:1558-1567`), which is what `get_recommendation_quality` aggregates.
- **The three recommendation test files pin the behaviour they claim to.**
  `tests/test_recommendation_service.py` (identity preservation, artist balance, skip
  suppression, provider-failure recovery, candidate sharing), `tests/test_recommendation_signals.py`
  (relevance, discovery ratio, aliases, reversible feedback), `tests/test_recommendation_bridge.py`
  (event contract, limits, request-id ordering) — 56 tests pass
  (`pytest tests/test_recommendation_service.py tests/test_recommendation_signals.py
  tests/test_recommendation_bridge.py tests/test_taste_profile.py tests/test_recommendation_ui.py
  tests/test_recommendation_feedback_ui.py -q` → `56 passed in 1.11s`).

---

### 4. Coverage gaps

- **The live provider behaviour was not exercised.** No network call was made (the audit rules
  forbid touching the network and the `network` marker is deselected), so F-WX-08-12
  (provider-pool starvation) is a hypothesis: the code path is confirmed, the magnitude is
  not. A live measurement would need a provider stub with controllable latency.
- **The wall-clock cost of the home page was not measured end to end.** All timings come from
  isolated probes against a synthetic 10 000-row SQLite file, not from the running app with
  a real library, a real disk and a real WebView. The relative costs (the ratio between the
  same-thread cache hit, the cross-thread rebuild and the `_rank_tracks` passes) are
  reliable; the absolute numbers will differ per machine.
- **The connection-leak rate was extrapolated, not observed in the app.** The probe
  reproduces pywebview's dispatch model (`Thread` per call, verified in
  `.venv_win/Lib/site-packages/webview/util.py:308`), but the real leak rate depends on how
  many bridge calls the shipped UI makes per session, which was not instrumented.
- **The privacy inventory covers the recommendation path only.** I did not audit whether the
  `history` table is exported or synced anywhere else (no backup feature was found: the only
  export is `core/api.py::export_playlist`, and `core/session.py` persists only the queue),
  but I did not check `services/zapret_service.py`, the proxy logs or the crash reporter.
- **The `artist_bindings` growth rate was not measured.** I confirmed that every artist-profile
  view adds one or two entries (`core/api.py:3461-3475`) and that there is no cap, but I did
  not count how many a typical session produces.
- **Windows-only behaviour of the WAL/`data_version` interplay was not stress-tested.**
  F-WX-08-1's fix depends on `PRAGMA data_version` being bumped for cross-connection commits
  under WAL on this platform; the experiment confirmed it works for the tested case
  (cross-thread `begin_listening_session` invalidated the profile) but a multi-writer stress
  test was not run.
- **The `history` retention question was not checked against product intent** — I could not
  find a spec that says how long the listening history should be kept, so F-WX-08-9 and
  F-WX-08-7 are stated as gaps in the current affordances rather than as violations of a
  documented rule.

---

### 5. Architecture improvements (ARCH)

**ARCH-1 — Extract the scoring core from the provider service.**
`RecommendationService` currently mixes four responsibilities: outbound provider fan-out
(`_collect_candidates`, `_collect_uncached_candidates`), the *model* of the user's taste
(`_profile`, `_seed_tracks`, `_known_tracks`, `_feedback`), the *scoring/ranking* function
(`_calculate_taste_weights`, `_rank_tracks`) and the *presentation* (`_format_ui_track`,
`_get_time_of_day_context`). The scoring half is pure and should be a separate, injectable,
deterministic module — which is exactly the slot `core/services/recommendation.py` was
supposed to occupy but never did (F-WX-08-10). Extracting it would make `_rank_tracks` unit
testable without a DB, a provider or a thread pool, and would let the alias map be computed
once per request (F-WX-08-2).

**ARCH-2 — One owner for "the user's taste".** Today the concept is decided in five places:
`services/taste_profile.py` (the weighted signal aggregation), `RecommendationService._calculate_taste_weights`
(the candidate scoring), `RecommendationService._feedback()` (the negative gate),
`_feed_tracks`'s cache signature (a fourth, independent derivation of "what the user likes"),
and the dead `core/services/recommendation.py` (a fifth, contradictory one). A single
`TasteModel` value object — with the profile, the negative feedback and the derived seeds —
produced once per request and passed down explicitly would remove the duplication and make
the cache keys derivable from the model instead of re-deriving it. Note that the model is
already built *inconsistently*: `RecommendationService._profile()` passes `settings=self.settings`,
but `get_smart_home_feed()` and `get_custom_artists()` build `UserTasteProfile()` **without**
settings (`services/recommendation_service.py:723` and `:651`), so the user's configured
`artist_aliases` are invisible to those two paths and they land on a *different* profile-cache
key than the rest of the service.

**ARCH-3 — The loop does not actually close: the negative feedback never reaches the taste
profile.** `UserTasteProfile` reads `history`, `tracks.is_favorite`, `tracks.is_downloaded`
and `playlist_tracks` — it has no representation of `blocked_artists` / `disliked_tracks`.
The feedback is applied as a post-hoc filter by the *service*, which is why the blocked
artist still occupies a slot in `profile.top_artists` and in the profile's own weights. A
model that can express "this artist, this track" as a first-class negative signal would let
the feedback change the *seeds* (and therefore the provider queries) rather than only the
final filter.

**ARCH-4 — Make the profile explainable to the user.** The backend computes and ships the
provenance of every recommendation (`recommendation_source`, `recommendation_relevance`,
`recommendation_seed_artists`, `recommendation_origin` —
`services/recommendation_service.py:105-108`), and the UI then **ignores all of it** (grep of
`ui/web_new_v2` finds no reader for any of those four fields). The user is shown
"Рекомендации" with no indication of why, and the profile itself (`UserTasteProfile.to_dict()`)
is never exposed through the bridge. Surfacing "because you listen to X" would close the
transparency gap that F-WX-08-7 leaves open, at zero extra cost — the data is already
computed and already crosses the bridge.

**ARCH-5 — Give the provider fan-out a per-request budget and a completion signal.** The
fan-out currently has a fixed 8 s wall-clock budget shared by a 4-worker pool (F-WX-08-12)
and no way to report "the providers did not answer" (F-WX-08-5). A small
`ProviderOutcome` result type (candidates + per-provider status + "timed out" flag) would
let the UI show an honest state.

**ARCH-6 — Give the bridge a connection policy.** The current model (one connection per
thread, pinned in `_all_conns`) assumes long-lived threads; pywebview hands out one-shot
threads (F-WX-08-3). Either a small explicit connection pool owned by `DatabaseManager`, or a
documented rule "every bridge call closes its thread's connection", would remove an
unbounded resource leak and make the DB cost per home load predictable.

**ARCH-7 — Decide whether `~/.nedotify/nedotify_storage.db` is user data that must be
erasable, and implement it.** The product has "clear cache" and "clear downloads" but no
"erase my history" (F-WX-08-7). Whatever the decision, the app should state it: either the
history is explicitly documented as permanent, or an erase action must exist. The two are
incompatible today and the user has no way to find out which one they are in.
