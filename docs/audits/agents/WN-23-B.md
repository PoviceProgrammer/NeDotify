## AREA WN-23 — Recommendations & taste profile — ROLE B

### 1. Scope reviewed

**Files opened (physical line ranges actually read, full files unless noted):**

- `services/recommendation_service.py` — **1–917** (full; the file is 917 physical lines, 827 non-empty).
- `services/taste_profile.py` — **1–634** (full; 563 non-empty).
- `core/services/recommendation.py` — **1–240** (full).
- `services/artist_identity.py` — **1–63** (full).
- `services/base_service.py` — **1–329** (full).
- `services/lastfm_service.py` — **40–89, 95–164, 178–227, 300–389** (key/handler/cache/request paths).
- `core/api.py` — **455–515** (offline interception), **2960–3019** (feedback/alias bridge), **3100–3199** (`clear_storage`, `get_wrapped_stats`), **3310–3419** (`get_popular_tracks`, `get_authentic_home_feed`), **3440–3499** (`_store_artist_binding`), **3536–3575** (`get_recommendations`, `get_track_wave`), **3730–3819** (`get_feed`, `get_home_artists`, `get_home_releases`, `get_home_mixes`), **4090–4120** (`clear_storage_cache`, `get_flow_tracks`).
- `core/database.py` — **140–219** (connection model), **270–339** (`history` schema + indexes), **1180–1246** (`get_all_tracks`, `get_favorite_tracks`, `get_most_played_tracks`, `get_user_history_tracks`), **1556–1638** (`begin_listening_session`, `get_recommendation_quality`, `get_history`), **1695–1721** (`get_most_played`, `get_top_artists`), **1723–1860** (`get_wrapped_stats`, `get_analytics_summary`), **2410–2489** (`close_thread_connection`, `close`).
- `core/app.py` — **180–299** (`recommendations` lazy property), **575–585** (candidate-executor shutdown).
- `core/settings.py` — **160–189** (`personalization` defaults), **530–589** (`get_category`, `reset_category`, `reset_all`).
- `services/artist_identity.py`, `utils/cache_manager.py` — **1–60, 120–179**.
- `ui/web_new_v2/js/home.js` — **170–205** (home load fan-out); `ui/web_new_v2/js/player.js` — **1510–1580** (flow autoplay).
- `.venv_win/Lib/site-packages/webview/util.py` — **295–315** (js_api thread dispatch).
- Tests read in full: `tests/test_recommendation_service.py` (1–204), `tests/test_recommendation_signals.py` (1–107), `tests/test_recommendation_bridge.py` (1–99), `tests/test_taste_profile.py` (1–175), `tests/test_recommendation_ui.py` (1–140), `tests/conftest.py` (1–176).

**Callees traced into other areas (defect in a callee is attributed to its owner, not duplicated here):**

| Callee | Area that owns its defects |
|---|---|
| `core/database.py` (`_get_connection`, `_all_conns`, `get_history`, `get_top_artists`, `get_wrapped_stats`, `get_analytics_summary`, `get_user_history_tracks`, `get_recommendation_quality`) | WN-12 (SQLite persistence layer) |
| `core/api.py::clear_storage` / `_delete_downloaded_files` / `_store_artist_binding` | WN-08 (settings & storage) / WN-09 (artist profile) |
| `core/settings.py::reset_all`, `SettingsManager.get` | WN-14 (settings manager) |
| `services/artist_identity.py::artist_aliases` | WN-18 (artist identity) |
| `services/lastfm_service.py` (HTTP + `~/.nedotify/cache/lastfm_cache.db`) | WN-21 (Last.fm provider) |
| `services/track_resolver.py`, `services/base_service.py` caches | WN-18 |
| `utils/cache_manager.py::clear_all` | WN-27 |

**Measurement scripts** (throwaway, under `%TEMP%\opencode\audit_reports\`): `_wn23b_measure_alias.py`, `_wn23b_measure_alias2.py`, `_wn23b_measure_memo.py`, `_wn23b_measure_memo2.py`, `_wn23b_measure_conns.py`, `_wn23b_measure_home.py`, `_wn23b_measure_final.py`, `_wn23b_measure_final2.py`, `_wn23b_measure_sig.py`. All used throwaway SQLite files under `%TEMP%`; `~/.nedotify/` was never touched (the Last.fm cache DB was only *read as source*, never instantiated against the real home).

---

### 2. Findings

#### F-WN-23-1  [P1] — `core/services/recommendation.py` is an orphaned second scoring engine: 240 lines, zero importers, a different feature model, and hard-coded fake artists

- **File:** `core/services/recommendation.py:1–240` (whole file)
- **Confirmed:** yes
- **Description:** The repo contains two recommendation cores. The live one is `services/recommendation_service.py` (imported lazily by `core/app.py:223`). The second, `core/services/recommendation.py`, defines `RecommendationEngine`, `run_recommendation` and `build_real_engine` — and **nothing in the repository imports any of them**. It is not a variant of the live engine: it scores on `bpm / energy / mood / acoustics / bass` features that the application's `tracks` table does not carry, it uses `random.uniform`/`random.sample` for the familiar/discovery ratio (the live engine uses a deterministic `discovery_ratio` setting), and `generate_artist_spotlights()` returns two fabricated rows ("Similar Artist", "Niche Artist") with the hard-coded reasons "Based on your tastes" / "High energy match". `build_real_engine` calls `db.get_all_tracks(limit=200)`, `db.get_history(limit=100)`, `db.get_favorite_tracks()`, `db.get_most_played(limit=50)` — all of which exist on `DatabaseManager`, but none of the profile inputs it consumes (`skips`, `repeats`, `subscriptions`) are ever produced by this codebase: `build_real_engine` hard-codes `"skips": {}` and `"repeats"` from play counts.
- **Cause:** The module was written against an imagined catalog schema (`artist_id`, `is_new_release`, `global_streams`, `viral_velocity`, `bpm`) that this application never adopted, and the live implementation was built in `services/` instead. Nothing ever deleted or wired it.
- **Trigger conditions:** Any future attempt to "enable" the richer engine — or any maintainer who greps for `RecommendationEngine` and edits this file — will do so against dead code that produces different results from the live path and that can fabricate artists.
- **User impact:** No direct user-visible impact today (it is unreachable). The risk is architectural: two engines with the same name, one of which is silently wrong and one of which a future change may wire in.
- **Evidence:**
  ```python
  # core/services/recommendation.py:35-45
  def _euclidean_distance(self, t1, t2):
      features = ["bpm", "energy", "mood", "acoustics", "bass"]
  # core/services/recommendation.py:160-176
  def generate_artist_spotlights(self):
      return {"similar_artists": [{"artist_id": "a_sim", "artist_name": "Similar Artist",
                                   "reason": "Based on your tastes"}],
              "niche_discovery": [{"artist_id": "a_niche", "artist_name": "Niche Artist",
                                   "reason": "High energy match"}]}
  # core/services/recommendation.py:213-214
  "skips": {}, "repeats": repeats,
  ```
  Repo-wide grep for `RecommendationEngine|run_recommendation|build_real_engine` returns **only the definitions in `core/services/recommendation.py`** plus an unrelated `User-Agent` string in `services/lastfm_service.py:157`. Repo-wide grep for `core.services.recommendation|from core.services import` returns **0 matches** (the only `core.services.*` import in the tree is `core.services.discord_rpc` in `tools/bench/pyprof_child.py:234`).
- **Reproduction / verification:**
  ```powershell
  rg "RecommendationEngine|run_recommendation|build_real_engine" -g "!android/**"
  rg "core\.services\.recommendation" -g "!android/**"
  ```
  Both return only `core/services/recommendation.py` itself (plus the unrelated User-Agent hit).
- **Suggested fix:** Delete `core/services/recommendation.py` (and the `core/services/` directory if `discord_rpc.py` is the only remaining member is not the convention). If a second engine is genuinely wanted, it must live under `services/` next to the live one and be covered by tests.
- **Fix side effects:** None at runtime — nothing imports it. The only risk is losing an unimplemented design sketch.
- **Discovered by:** B

---

#### F-WN-23-2  [P2] — The 60 s taste-profile memo can never hit across threads: the revision key embeds the caller's own connection object

- **File:** `services/taste_profile.py:357–371` (+ `core/database.py:155, 179–201`)
- **Confirmed:** yes
- **Description:** The memo was introduced with the explicit comment *"60s profile memoisation (identical profiles were recomputed per section)"* (`services/taste_profile.py:339`). Its validity check compares a *revision* tuple that contains the `sqlite3.Connection` **object itself**:
  ```python
  @staticmethod
  def _connection_revision(conn) -> Any:
      data_version = conn.execute('PRAGMA data_version').fetchone()[0]
      schema_version = conn.execute('PRAGMA schema_version').fetchone()[0]
      return (conn, conn.total_changes, data_version, schema_version)
  ```
  `core/database.py` hands every thread its own connection (`self._local = threading.local()`, `_get_connection()` at `:179-201`). Two different threads therefore produce two different revision tuples for the *same* database, so `_cache_get`'s `if entry.get('revision') != revision: return None` always misses. The memo degenerates into a per-connection cache.
- **Cause:** The revision must detect "did anyone write?". `PRAGMA data_version` + `conn.total_changes` already do that per connection, but the tuple also embeds the connection *identity*, which is thread-scoped by construction.
- **Trigger conditions:** Whenever two threads build the profile within the 60 s TTL. In the shipped app this is the normal case: the recommendation service dispatches onto the shared 8-worker pool (`services/base_service.py:124`), and the bridge dispatches each `js_api` call onto its own thread (`.venv_win/Lib/site-packages/webview/util.py:308` — `thread = Thread(target=_call); thread.start()`).
- **User impact:** The stated optimisation never happens; every profile build re-runs 7 SELECTs and the full Python-side aggregation, on every home load and every track wave. On a large library this is pure wasted CPU on the recommendation path.
- **Evidence:**
  ```python
  # services/taste_profile.py:368
  return (conn, conn.total_changes, data_version, schema_version)
  # core/database.py:155,180
  self._local = threading.local()
  if not hasattr(self._local, "connection") or self._local.connection is None:
  ```
  Measured (throwaway DB, 40 history rows):
  ```
  === MAIN thread: two consecutive builds ===
    build #1 SELECTs = 6
    build #2 SELECTs = 0   <- memo hit
  === WORKER thread: two consecutive builds on the SAME worker thread ===
    build #1 SELECTs = 7
    build #2 SELECTs = 0   <- memo hit inside the thread
    worker conn id = 1999784878832, main conn id = 1999784878352  (different objects)
  === 5 sequential bridge-style calls, alternating threads ===
    call 1 on a fresh thread -> 7 SELECTs
    call 2 on a fresh thread -> 7 SELECTs
    ... (5/5 misses)
  revision tuple = (<sqlite3.Connection object at 0x...>,) -> element 0 is the Connection object: True
  ```
  And end-to-end through the real bridge methods (real `DatabaseManager`, real `RecommendationService`, provider clients stubbed, 120 history rows + 8 favourites):
  ```
  === one home-page load: get_feed + get_home_releases + get_home_mixes ===
    build_from_db calls = 3  (cache misses = 3, SELECTs = 21)
  === repeated: 5 sequential get_feed() calls ===
    build_from_db calls = 2  (cache misses = 2, SELECTs = 12)
  ```
  i.e. **3 profile builds per home page load, every one of them a full miss.**
- **Reproduction / verification:** `_wn23b_measure_memo2.py` (script quoted in the Evidence block). Reproduce the shape with any two-thread harness that calls `UserTasteProfile().build_from_db(db)` from two threads and counts `SELECT` statements via `conn.set_trace_callback`.
- **Suggested fix:** Drop the connection object from the revision tuple. `PRAGMA data_version` is explicitly designed for cross-connection change detection (it changes when *another* connection commits), and `conn.total_changes` covers writes on this connection; together with `schema_version` they are sufficient. If per-connection identity is genuinely needed, key the memo by the database path rather than the connection, and hold a single shared connection for the profile build.
- **Fix side effects:** A shared revision widens the cache hit window — the memo must then be invalidated correctly when a *different* connection commits. `PRAGMA data_version` provides exactly that, but it must be read on the same connection every time; mixing `data_version` across connections is documented as "undefined" by SQLite, so the fix should use one connection per database for the profile build (or verify `data_version` semantics on the target SQLite build).
- **Discovered by:** B

---

#### F-WN-23-3  [P2] — The artist-alias table is rebuilt from scratch for every candidate and every favourite: O(candidates × favourites) table rebuilds, each O(bindings)

- **File:** `services/recommendation_service.py:147–149, 157–159, 209–225, 295–300, 334, 408`
- **Confirmed:** yes
- **Description:** `artist_aliases(settings)` (`services/artist_identity.py:13–32`) reconstructs the whole alias map from settings on every call — it copies `DEFAULT_ALIASES`, applies the user map, then walks **every** entry of `personalization.artist_bindings` and computes **two SHA-256 digests per binding**. The recommendation service calls it from `_artist_key` (`:148`) and `_content_key` (`:159`), and both of those are called *per candidate* inside `_calculate_taste_weights`:
  ```python
  def _calculate_taste_weights(self, candidate, taste_profile):
      artist = self._artist_key(candidate)                      # -> artist_aliases()
      scores = {(a.get('identity_key') or self._artist_key(a.get('name'))): ...   # -> per top artist
                for a in taste_profile.top_artists}
      recent = max((1 - i / 20 for i, t in enumerate(taste_profile.recent_history[:20])
                    if self._artist_key(t) == artist), default=0)                 # -> per recent track
      favorite = any(self._artist_key(t) == artist for t in taste_profile.favorite_tracks)  # -> per FAVOURITE
  ```
  So the rebuild count is `O(candidates × (favourites + recent + top_artists))`, and each rebuild is `O(bindings)` with two SHA-256 digests per binding.
- **Cause:** The alias table is a *derived, immutable-per-settings-revision* value, but it is treated as a pure function call at every use site instead of being memoised per settings revision.
- **Trigger conditions:** Any recommendation ranking. The cost scales with (a) the number of artist pages the user has opened — `core/api.py:3461–3475` `_store_artist_binding` writes one `artist_bindings` entry per artist profile view, with **no cap** — and (b) the size of the user's favourites list, which `UserTasteProfile` caps at `HISTORY_LIMIT = 1500` (`services/taste_profile.py:22`).
- **User impact:** Ranking latency grows super-linearly with library size. Measured with 50 candidates: **203 ms** of pure alias-table rebuilding when the user has 1 000 favourites, and 88 ms with 200 configured `artist_bindings` and only 50 candidates. `_rank_tracks` runs 3–4× per home load (feed, releases, mixes ×2), so a heavy user pays this repeatedly.
- **Evidence:**
  ```python
  # services/recommendation_service.py:147-149
  def _artist_key(self, value):
      aliases = artist_aliases(self.settings)
      return track_key(value, aliases)[0] if isinstance(value, dict) else canonical_artist(value, aliases)
  # services/recommendation_service.py:157-159
  def _content_key(self, track):
      return track_key(track, artist_aliases(self.settings))
  # services/artist_identity.py:19-32  (the O(bindings) rebuild)
  bindings = settings.get('personalization', 'artist_bindings', {}) if settings else {}
  ...
      digest = hashlib.sha256(str(refs[source]).encode()).hexdigest()
  ```
  Measured (alias rebuilds counted by monkey-patching `services.recommendation_service.artist_aliases`):
  ```
  === _rank_tracks(50 candidates) ===
    bindings=   0 candidates=  10 -> artist_aliases() calls=    78  elapsed=   1.2 ms
    bindings=   0 candidates=  50 -> artist_aliases() calls=   328  elapsed=   1.7 ms
    bindings=  50 candidates=  50 -> artist_aliases() calls=   328  elapsed=  23.4 ms
    bindings=  50 candidates= 200 -> artist_aliases() calls=  1228  elapsed=  84.5 ms
    bindings= 200 candidates=  50 -> artist_aliases() calls=   328  elapsed=  88.6 ms
  === per-rebuild cost ===
    bindings=  50 -> 0.068 ms per rebuild
    bindings= 200 -> 0.297 ms per rebuild
  === feedback / favourite volume (50 candidates, 0 bindings) ===
    disliked=    0 favourites=    0 -> calls=   274  elapsed=   1.6 ms
    disliked= 1000 favourites=    0 -> calls=  1274  elapsed=   4.7 ms
    disliked=    0 favourites=  200 -> calls= 10874  elapsed=  38.3 ms
    disliked=    0 favourites= 1000 -> calls= 53274  elapsed= 203.1 ms
    disliked= 1000 favourites= 1000 -> calls= 54274  elapsed= 208.6 ms
  ```
- **Reproduction / verification:** `_wn23b_measure_alias.py` and `_wn23b_measure_alias2.py` (both under `%TEMP%\opencode\audit_reports\`). The call count can also be observed with `cProfile` on `_rank_tracks`, or by adding a counter to `services/artist_identity.artist_aliases`.
- **Suggested fix:** Memoise the alias table per settings revision (a monotonically increasing revision counter on `SettingsManager`, or a hash of the two raw settings blobs), and pass the resolved table into `_artist_key` / `_content_key` instead of recomputing it. Additionally, hoist the per-candidate `scores` dict, the `recent` lookup and the `favorite` lookup out of `_calculate_taste_weights` and precompute them once per ranking.
- **Fix side effects:** A cached alias table must be invalidated when the user edits `personalization.artist_aliases` / `artist_bindings` (both are writable from the bridge: `core/api.py:3002–3018` `set_artist_alias`, `core/api.py:3461–3475` `_store_artist_binding`, and `save_personalization` writes any key of the category — see WN-08-A). A settings-revision counter is the safe invalidation source.
- **Discovered by:** B

---

#### F-WN-23-4  [P2] — The recommendation path opens a SQLite connection on every throwaway bridge thread and never releases it; `DatabaseManager._all_conns` grows one-for-one

- **File:** `services/taste_profile.py:60–68, 523–533` (the caller) + `core/database.py:155, 179–201, 2413–2438` (the owner)
- **Confirmed:** yes
- **Description:** `UserTasteProfile.build_from_db` resolves the connection via `self._get_conn(db)` → `db.conn` → `DatabaseManager._get_connection()`. Because `DatabaseManager` is thread-local, **each thread that builds a profile opens a brand-new `sqlite3.Connection`**, and that connection is inserted into `self._all_conns` — a plain `set` that holds a **strong reference**, so the connection object can never be garbage-collected and never be closed by its own (already dead) thread. The only method that removes entries is `close_thread_connection()`, and the recommendation path never calls it; the only in-tree callers are `core/proxy.py:482` (per HTTP request) and `DatabaseManager.close()`.
- **Cause:** The recommendation path treats the `DatabaseManager` as if it were a connection pool. It is a thread-affine handle with a bookkeeping set; the path never participates in the "close when the thread is done" contract that `close_thread_connection()` was written for.
- **Trigger conditions:** Every `js_api` call that touches the DB. pywebview dispatches each `js_api` call on a **new** thread (`.venv_win/Lib/site-packages/webview/util.py:308`), so `AppApi.get_feed` / `get_home_mixes` / `get_home_releases` / `get_popular_tracks` each open a fresh connection on a fresh thread that dies immediately afterwards — while the connection stays pinned in `_all_conns` until process exit.
- **User impact:** Unbounded growth of open SQLite handles (one per distinct thread that ever touched the DB) for the lifetime of the process, plus file-handle pressure on `nedotify_storage.db` / `-wal` / `-shm`. `DatabaseManager.close()` cannot reclaim them either, and it says so explicitly:
  > `"%d database connection(s) could not be closed from the main thread (created on another thread); they were released when their thread exited."` (`core/database.py:2484–2489`)
  
  (That message is itself inaccurate: the connections are *not* released when the thread exits, because `_all_conns` keeps them alive.)
- **Evidence:**
  ```python
  # core/database.py:155,158,198-201
  self._local = threading.local()
  self._all_conns = set()
  ...
  self._local.connection = conn
  with self._conns_lock:
      self._all_conns.add(conn)
  ```
  Measured (50 js_api-style calls, each on its own thread):
  ```
  after init:            _all_conns = 1
  after   1 js_api-style calls: _all_conns = 2
  after   5 js_api-style calls: _all_conns = 6
  after  10 js_api-style calls: _all_conns = 11
  after  25 js_api-style calls: _all_conns = 26
  after  50 js_api-style calls: _all_conns = 51
  after gc.collect():     _all_conns = 51
  ```
  And the shutdown error the app itself logs:
  ```
  6 database connection(s) could not be closed from the main thread (created on another thread);
  they were released when their thread exited. First error: SQLite objects created in a thread
  can only be used in that same thread.
  ```
- **Reproduction / verification:** `_wn23b_measure_conns.py` (a `DatabaseManager` on a throwaway file; 50 threads each doing `db.conn.execute("SELECT COUNT(*) FROM tracks")`).
- **Suggested fix:** In the recommendation path, either (a) close the thread's connection when the worker finishes (`db.close_thread_connection()` in the `finally` of the pool task), or (b) give `UserTasteProfile` a short-lived dedicated connection that it opens and closes itself. The owning defect — `_all_conns` being a strong-ref set that pins connections forever — belongs to **WN-12 (`core/database.py`)**; this finding is WN-23's contribution (the recommendation path is a caller that opens and abandons connections).
- **Fix side effects:** Closing the connection after each profile build means the next build pays `sqlite3.connect` + 7 PRAGMAs (~1 ms). If the profile build is moved to a single dedicated connection (see F-WN-23-2), the cost disappears.
- **Discovered by:** B

---

#### F-WN-23-5  [P2] — A provider outage is indistinguishable from "no taste", and empty candidate sets are never negatively cached

- **File:** `services/recommendation_service.py:396–400, 352–357, 474–479` + `core/api.py:3747, 3775, 3789`
- **Confirmed:** yes
- **Description:** Provider exceptions inside the candidate fan-out are swallowed at DEBUG level:
  ```python
  for future, (source, seed_artist, _) in zip(futures, jobs):
      if future not in done: continue
      try:
          items = future.result() or []
      except Exception as exc:
          self.logger.debug('Recommendation provider unavailable: %s', exc)
          continue
  ```
  The result is that a dead provider yields *zero candidates*, and the feed then falls through to the empty-result path. There is **no negative cache**: `_collect_candidates` stores the candidate list only `if candidates:` (`:354–355`), and `_feed_tracks` stores the feed only `if tracks and candidates:` (`:477–478`). Every subsequent home load re-runs the whole provider fan-out (up to the 12 s deadline at `:367`).
  The two "no results" states then collapse into one payload: an empty taste profile falls back to the 8 curated welcome tracks (`:474–475`), while **any** non-empty profile plus a provider outage yields `[]`. On the bridge, `core/api.py:3747/3775/3789` discard the error text entirely (`error_callback=lambda _error: self._emit("feed_ready", [])`).
- **Cause:** Failure is modelled as "there is nothing to recommend" rather than "the provider is unreachable", and the cache stores only successes.
- **Trigger conditions:** Any provider outage (YouTube / SoundCloud / Last.fm unreachable, rate-limited, or blocked by the user's proxy) — exactly the conditions the app is designed to survive (the proxy, zapret, offline mode all exist for that reason).
- **User impact:** With any listening history at all, a provider outage turns the entire home page into an empty state that looks identical to "we don't know you yet". The user has no way to tell that the network is the problem. The curated fallback that *would* have made the failure visible only applies to users with no history. Meanwhile the app keeps retrying the full fan-out on every single home load, burning the 12 s budget each time.
- **Evidence:**
  ```python
  # services/recommendation_service.py:354-355
  candidates = self._collect_uncached_candidates(seeds, artists, limit)
  if candidates:
      self.set_search_cache(key, [dict(t) for t in candidates])
  # services/recommendation_service.py:477-478
  if tracks and candidates:
      self.set_search_cache(key, [dict(t) for t in tracks])
  # services/recommendation_service.py:474-475
  if not tracks and profile.is_empty() and not profile.recent_history:
      tracks = self._rank_tracks(CURATED_WELCOME_TRACKS, profile, max_results)
  ```
  Measured with a provider that always raises:
  ```
  === 3. empty candidate set is NOT cached -> every home load re-runs providers ===
    home load #1 -> provider calls made: 1
    home load #2 -> provider calls made: 1
    home load #3 -> provider calls made: 1
  === 4. provider down + non-empty profile -> the feed is [] (same as 'no taste') ===
    _feed_tracks(profile, 10) with the provider down -> []
  === 5. empty profile + provider down -> curated welcome tracks (no error surfaced) ===
    _feed_tracks(empty_profile, 10) -> ['Blinding Lights', 'Levitating', 'Love The Way You Lie',
                                      'Bohemian Rhapsody', 'Hymn for the Weekend', 'Shape of You',
                                      'Believer', 'bad guy']
  ```
- **Reproduction / verification:** `_wn23b_measure_final2.py`. Also visible in the shipped test: `tests/test_recommendation_service.py:154–161` (`test_provider_failure_can_recover_on_next_feed`) asserts that a failing provider yields `[]` and that the *next* call recovers — i.e. the empty result is the intended, pinned behaviour.
- **Suggested fix:** (a) Distinguish "provider failed" from "nothing matched": track per-source failures in `_collect_uncached_candidates` and surface a `degraded` flag on the payload so the UI can say "provider unreachable" instead of "no recommendations". (b) Cache the *empty* candidate set for a short TTL (e.g. 30–60 s) so a down provider costs one fan-out per minute instead of one per home load. (c) Keep the error string instead of discarding it in `core/api.py:3747/3775/3789` (that bridge change belongs to WN-10).
- **Fix side effects:** Negative caching delays recovery by the TTL; the existing test `test_provider_failure_can_recover_on_next_feed` (`tests/test_recommendation_service.py:154`) would need its second call moved past the TTL or the cache invalidated on failure.
- **Discovered by:** B

---

#### F-WN-23-6  [P2] — There is no user-facing way to erase the taste signal; `clear_storage("all")` deletes the audio but leaves the profile (and the DB flags) fully intact

- **File:** `core/api.py:3105–3154` (the bridge action) + `utils/cache_manager.py:22–29, 152–156` + `services/lastfm_service.py:180–202`
- **Confirmed:** yes
- **Description:** The taste profile is **not** a separate artefact: it is derived on the fly from `history`, `tracks.is_favorite`, `tracks.is_downloaded` and `playlist_tracks` in the plaintext SQLite database at `~/.nedotify/nedotify_storage.db`. There is no `taste_profile` table, no export, and no delete path:
  - `AppApi.clear_storage` (`:3105–3136`) clears the cache manager and, for `"all"`, calls `_delete_downloaded_files()`.
  - `_delete_downloaded_files` (`:3138–3154`) only does `os.remove(fp)` — it does **not** clear `tracks.file_path` / `tracks.is_downloaded`.
  - `CacheManager.clear_all` (`utils/cache_manager.py:152–156`) clears `~/.nedotify/covers`, `~/.nedotify/streams`, `~/.nedotify/temp` — **not** `~/.nedotify/cache/lastfm_cache.db`, which is a separate plaintext SQLite store of Last.fm responses (including the response to `user.getTopArtists` for the configured username).
  - `SettingsManager.reset_all` (`core/settings.py:546–549`) resets **settings** only — it clears `personalization.blocked_artists` / `disliked_tracks` / `artist_aliases` / `artist_bindings` (`core/settings.py:166–176`) but leaves the listening history untouched.
  - A repo-wide grep for `DELETE FROM history` returns **no match** in the Windows desktop product — the `history` table only shrinks when a track row is deleted, because of `FOREIGN KEY (track_id) REFERENCES tracks(id) ON DELETE CASCADE` (`core/database.py:280`).
- **Cause:** The taste signal is treated as an emergent property of the library rather than as user data with a lifecycle.
- **Trigger conditions:** A user who wants the app to stop using their listening history has no way to do it: not through Settings, not through "clear cache", not through "clear storage (all)".
- **User impact:**
  1. **No erasure path.** The only way to shrink the history is to delete tracks one by one from the library. The behaviour is consistent with the project rule "`~/.nedotify/` is the user's library — clearing it is not a cleanup step", but the rule says the app must not clear it *silently*; it does not say the user must be unable to clear it deliberately.
  2. **Stale download flags.** After `clear_storage("all")` the audio files are gone but the DB still says `is_downloaded = 1` and `file_path = '<deleted>'`. The taste profile therefore still counts those tracks with `WEIGHT_DOWNLOAD = 3.0` (`services/taste_profile.py:37`) as strong signals, and `_rank_tracks` prefers them as "familiar, playable" tracks (`services/recommendation_service.py:287`, `known_rows` at `:248–254`). The feed therefore keeps recommending tracks whose audio no longer exists.
  3. **A taste-adjacent artefact survives "clear cache".** `~/.nedotify/cache/lastfm_cache.db` keeps the plaintext Last.fm payloads (including the user's top-artist list) indefinitely; no cache-clearing action removes it.
- **Evidence:**
  ```python
  # core/api.py:3138-3154
  def _delete_downloaded_files(self) -> int:
      removed = 0
      tracks = self._core.db.get_downloaded_tracks() or []
      for t in tracks:
          fp = t.get("file_path")
          if not fp: continue
          try:
              if os.path.isfile(fp):
                  os.remove(fp); removed += 1
          except OSError as e:
              logger.warning("clear_storage: could not remove %s: %s", fp, e)
      return removed
  # utils/cache_manager.py:22-29
  self._covers_dir  = os.path.join(self._base_dir, "covers")
  self._streams_dir = os.path.join(self._base_dir, "streams")
  self._temp_dir    = os.path.join(self._base_dir, "temp")
  # services/lastfm_service.py:180-187
  base_dir = os.path.join(os.path.expanduser('~'), '.nedotify', 'cache')
  ... return os.path.join(base_dir, 'lastfm_cache.db')
  ```
  Repo-wide grep `DELETE FROM history` → no match in `core/`, `services/`, `audio/`, `utils/`, `ui/` (the only hits are under `android/`, which is out of scope).
- **Reproduction / verification:** Read `core/api.py:3105–3154` and `utils/cache_manager.py:22–29`; `rg "DELETE FROM history" -g "!android/**"` returns nothing. For the stale-flag consequence: call `api.clear_storage("all")` on a DB with a downloaded track, then inspect `db.get_downloaded_tracks()` (still returns the row with its `file_path`) and `UserTasteProfile().build_from_db(db).downloaded_tracks` (still populated).
- **Suggested fix:** (a) Clear `tracks.file_path` / `tracks.is_downloaded` in `_delete_downloaded_files` (that bridge defect belongs to **WN-08**; this is its WN-23 consequence). (b) Add an explicit, confirmed user action ("erase listening history / reset taste profile") that deletes the `history` rows and invalidates the profile memo — consistent with the "ask first" rule. (c) Include `~/.nedotify/cache/lastfm_cache.db` in the cache-clearing surface (WN-27 / WN-21).
- **Fix side effects:** (a) is safe and makes the profile consistent with the disk. (b) destroys the user's listening history, so it must be explicit, opt-in and confirmed — and must also clear the `recommendation_context` telemetry that `get_recommendation_quality` (`core/database.py:1569`) depends on, or that report will silently become empty.
- **Discovered by:** B

---

#### F-WN-23-7  [P3] — The user's Last.fm username and the artist+title of their recent plays are sent to Last.fm with no in-app disclosure

- **File:** `services/recommendation_service.py:495–541` (`_get_merged_seed_artists`), `:382–387` (`_collect_uncached_candidates`)
- **Confirmed:** yes
- **Description:** When a Last.fm API key is configured, the recommendation path sends three kinds of user-derived data to `ws.audioscrobbler.com`:
  1. **The user's Last.fm username** — `settings.get('auth','lastfm_username')` or `$LASTFM_USERNAME` → `self.lastfm.user.getTopArtists(username, limit=5)` (`:516`). The response is the user's *entire* Last.fm top-artist list, which is a direct read of their listening habits on another service.
  2. **The artist + title of a recently played track** — `self.lastfm.track.getSimilar(seed['artist'], seed['title'], limit=10)` (`:385`), where `seeds` come from the taste profile (the user's own recent/favourite tracks).
  3. **The user's top artist names** — `self.lastfm.artist.getTopTracks(artist, limit=6)` (`:387`), and again in `get_smart_home_feed` (`:756, :801, :835`).
  The disclosure is opt-in by the API key (without one, `LastFMService._api_request` short-circuits at `services/lastfm_service.py:315–318` and no request is made), but nothing in the UI states what is sent, and the response is persisted in plaintext at `~/.nedotify/cache/lastfm_cache.db` where no cache action reaches it (see F-WN-23-6).
- **Cause:** The service treats the Last.fm account as a personalization source without an explicit, documented consent boundary in the product surface.
- **Trigger conditions:** A Last.fm API key is configured (env var `LASTFM_API_KEY` or `auth.lastfm_api_key`), and the user has any listening history. The `user.getTopArtists` call is fire-and-forget on the candidate executor (`:526`), so it happens on the first recommendation request after startup.
- **User impact:** Listening behaviour and the user's Last.fm identity leave the machine. The scope is bounded (artist/title pairs and top artists, not raw history), and it is entirely avoidable by not configuring a key — but the user is never told.
- **Evidence:**
  ```python
  # services/recommendation_service.py:498-499
  username = self.settings.get('auth', 'lastfm_username', '') if self.settings else ''
  username = username or os.getenv('LASTFM_USERNAME', '')
  # services/recommendation_service.py:514-517
  names = [a['name'] for a in (self.lastfm.user.getTopArtists(username, limit=5) or [])
           if isinstance(a, dict) and a.get('name')]
  # services/recommendation_service.py:382-387
  if self._lastfm_enabled():
      for seed in seeds[:2]:
          if seed.get('artist') and seed.get('title'):
              add_job('lastfm_similar', seed['artist'], lambda seed=seed: self.lastfm.track.getSimilar(seed['artist'], seed['title'], limit=10))
      for artist in artists[:2]:
          add_job('lastfm_artist', artist, lambda artist=artist: self.lastfm.artist.getTopTracks(artist, limit=6))
  # services/lastfm_service.py:315-318  (no key -> no network)
  if not self.available:
      self.logger.debug(f'Skipping Last.fm {method}: no usable API key configured')
      return self._get_stale_cache(cache_key)
  ```
- **Reproduction / verification:** Read `services/recommendation_service.py:495–541` and `:382–387`; confirm the no-key short-circuit at `services/lastfm_service.py:315–318`; confirm the on-disk cache path at `services/lastfm_service.py:180–187`.
- **Suggested fix:** Surface the Last.fm disclosure in the Settings UI next to the API-key field (what is sent, to whom, and how to turn it off), and give the scrobble import its own opt-in toggle independent of the API key. Consider dropping the `user.getTopArtists` import entirely — it contributes 5 artists to the seed list and is the most identifying of the three disclosures.
- **Fix side effects:** Turning the scrobble import off removes `LASTFM_USERNAME`-based seeds; `_get_merged_seed_artists` already falls back to the local profile, so the feed stays populated.
- **Discovered by:** B

---

#### F-WN-23-8  [P3] — `get_custom_artists` and `get_smart_home_feed` build the profile **without** `settings`, so the user's alias table is not applied

- **File:** `services/recommendation_service.py:651` and `:723` (vs `:174`)
- **Confirmed:** yes
- **Description:** Three call sites build the taste profile; two of them omit the settings object:
  ```python
  # :174  (correct)
  profile = UserTasteProfile(settings=self.settings).build_from_db(self.db) if self.db else UserTasteProfile(settings=self.settings)
  # :651  (get_custom_artists)
  taste_profile = UserTasteProfile().build_from_db(self.db)
  # :723  (get_smart_home_feed)
  taste_profile = UserTasteProfile().build_from_db(self.db)
  ```
  `UserTasteProfile.__init__` computes `self.artist_aliases = artist_aliases(settings)` (`services/taste_profile.py:43`), and `artist_aliases(None)` yields only `DEFAULT_ALIASES` — the user's `personalization.artist_aliases` and `personalization.artist_bindings` are silently dropped. The same profile is then used for artist identity everywhere downstream (`identity_track_key(row, self.artist_aliases)` at `services/taste_profile.py:234`).
- **Cause:** `UserTasteProfile`'s constructor takes an optional `settings` that silently changes the *identity model*, so a caller that forgets it gets a different — not an error — result.
- **Trigger conditions:** Any call to `get_custom_artists` or `get_smart_home_feed`. **Both are currently unreachable** — `get_custom_artists` has no caller anywhere in the repo, `get_smart_home_feed` is called only by `get_authentic_home` (also uncalled), and `get_authentic_home_feed` (`core/api.py:3337`) has no `ui/web_new_v2/**` call site (independently confirmed: grep of `ui/web_new_v2` for `get_authentic_home_feed` returns nothing; `tests/test_recommendation_ui.py:54` even asserts it is *not* called).
- **User impact:** None today (dead paths). The defect becomes live the moment either method is wired to the UI: aliased artists would be counted as two different artists, the "Микс: <artist>" sections would not match the feed's artist identities, and blocked artists filtered through the aliased path would leak through.
- **Evidence:**
  ```python
  # services/taste_profile.py:41-43
  def __init__(self, settings=None):
      self.settings = settings
      self.artist_aliases = artist_aliases(settings)
  # services/artist_identity.py:13-18
  def artist_aliases(settings=None):
      aliases = dict(DEFAULT_ALIASES)
      configured = settings.get('personalization', 'artist_aliases', {}) if settings else {}
  ```
  Measured with a user alias `моект → MOEKT`:
  ```
  aliases with settings   : {'фараон': 'PHARAOH', 'моект': 'MOEKT'}
  aliases without settings: {'фараон': 'PHARAOH'}
  track_key(with)    = ('moekt', 't')
  track_key(without) = ('моект', 't')
  ```
- **Reproduction / verification:** `_wn23b_measure_alias2.py` (last block). Confirmed reachability with `rg "get_custom_artists|get_smart_home_feed|get_authentic_home" -g "!android/**" -g "!docs/**"`.
- **Suggested fix:** Either delete the two unreachable methods (preferred — they duplicate `get_feed`/`get_mixes` with a different, broken profile construction), or make `settings` a **required** constructor argument of `UserTasteProfile` so the omission becomes a `TypeError` instead of a silent behaviour change.
- **Fix side effects:** Making `settings` required would break the ~30 call sites in `tests/` that construct `UserTasteProfile()` with no arguments (`tests/test_recommendation_service.py:70, 82, 94, 122, 179`; `tests/test_recommendation_signals.py:45, 57, 83`; `tests/test_taste_profile.py:17–160`). Those tests would need a settings stub.
- **Discovered by:** B

---

#### F-WN-23-9  [P2] — `get_flow_tracks` runs the entire candidate collection inline on the js_api worker thread, unlike every other recommendation entry point

- **File:** `core/api.py:4110–4120` → `services/recommendation_service.py:901–917` → `:366–449`
- **Confirmed:** yes
- **Description:** Every other recommendation entry point goes through `_async_recommendation` (`:481–493`), which submits the work to the shared 8-worker pool and returns immediately. `get_flow_tracks` does not:
  ```python
  # core/api.py:4118-4119
  return self._core.recommendations.get_flow_tracks_sync(seed_track, limit=limit, exclude_ids=exclude_ids)
  # services/recommendation_service.py:914
  return task()          # <- runs INLINE on the calling thread
  # services/recommendation_service.py:916-917
  def get_flow_tracks_sync(self, seed_track, limit=6, exclude_ids=None):
      return [dict(t, recommendation_origin='flow') for t in (self.get_wave_for_track(seed_track, limit=limit, exclude_ids=exclude_ids) or [])]
  ```
  `task()` calls `_collect_candidates` → `_collect_uncached_candidates`, which submits the provider jobs to the candidate pool and then **blocks** in `wait(futures, timeout=min(8.0, max(0, deadline - time.monotonic())))` (`:389`), followed by a metadata-resolution pass with `timeout=remaining` against a 12 s deadline (`:367, :435–446`). The frontend awaits the bridge call (`ui/web_new_v2/js/player.js:1553`).
- **Cause:** The synchronous convenience wrapper was never converted to the async/callback convention that the rest of the service uses.
- **Trigger conditions:** Every flow-autoplay request (i.e. whenever the queue runs low during playback and flow mode is enabled). The UI thread is *not* blocked (pywebview runs the call on its own thread), but the JS `await` is parked for the whole fan-out, and the profile is rebuilt synchronously on that thread too.
- **User impact:** Flow autoplay stalls for as long as the providers take (up to ~12 s) instead of returning promptly; every stall also pays a full profile rebuild (F-WN-23-2) and the alias-table rebuild cost (F-WN-23-3). Offline mode is handled (`core/api.py:492–493` short-circuits `get_flow_tracks` to `[]`), so this is an online-mode issue only.
- **Evidence:**
  ```python
  # services/recommendation_service.py:367, 388-391, 435-446
  deadline = time.monotonic() + 12.0
  futures = [self._candidate_executor.submit(work) for _, _, work in jobs]
  done, pending = wait(futures, timeout=min(8.0, max(0, deadline - time.monotonic()))) if futures else (set(), set())
  ...
  remaining = max(0, deadline - time.monotonic())
  if metadata and remaining > 0:
      resolved = self.resolver.resolve_tracks(pairs, timeout=remaining)
  # ui/web_new_v2/js/player.js:1553
  const candidates = await bridge.get_flow_tracks(request.seedData, limit, exclusions);
  ```
- **Reproduction / verification:** Trace `core/api.py:4119` → `services/recommendation_service.py:917` → `:914`; the `return task()` at `:914` is reached because `callback` is `None` (`:911`). The other entry points are visibly async: `:481–493` (`_async_recommendation` → `self.submit(run)`), `:566`, `:624`, `:866`.
- **Suggested fix:** Give `get_flow_tracks` the same callback/`track_wave_ready`-style contract as `get_track_wave` (`core/api.py:3555–3581`), or at minimum move the candidate collection off the calling thread and return a promise. A short timeout on the candidate wait (e.g. 2–3 s) would also bound the stall.
- **Fix side effects:** Converting to async changes the bridge contract and the `js/player.js:1553` call site (WN-29's file). A timeout-only fix is local to `services/recommendation_service.py` but may starve the flow of candidates on slow connections.
- **Discovered by:** B

---

#### F-WN-23-10  [P2] — Four different definitions of "top artist" and three of "recently played" feed the same home page

- **File:** `services/taste_profile.py:269–273, 143–153` vs `core/database.py:1708–1721, 1695–1706, 1772–1789, 1599–1624, 1239–1246` vs `core/api.py:3761, 3770, 3742, 3784, 3323, 3396`
- **Confirmed:** yes
- **Description:** The area has no single source of truth for "what the user listens to". The definitions in production are:

  | Concept | Definition | Where used |
  |---|---|---|
  | top artist (profile) | `like/download=3, completed=2, play=1`, × 30-day recency half-life | `_get_merged_seed_artists`, `_calculate_taste_weights` |
  | top artist (DB) | `SUM(play_count) GROUP BY artist`, no recency, no like/download weight | `core/api.py:3761` (`get_home_artists`), `:3770` (`get_home_releases`) |
  | most played (DB) | `WHERE play_count > 0 ORDER BY play_count DESC` | `services/recommendation_service.py:604` (charts fallback) |
  | top artist (wrapped) | `COUNT(h.id) GROUP BY LOWER(t.artist)` over a period | `core/database.py:1784` → `core/api.py:3156` |

  | "Recently played" | Definition | Where used |
  |---|---|---|
  | `db.get_history(limit)` | one row **per track**, `GROUP BY t.id`, `MAX(played_at)` | `core/api.py:3323, 3396, 3742, 3784` |
  | `db.get_user_history_tracks(limit)` | one row **per listening event**, no dedup | `core/api.py:3340–3343` (`get_authentic_home_feed`) |
  | `profile.recent_history` | 1 500 rows ordered by `played_at`, sliced to 50 | `services/taste_profile.py:143–153` |

  The two shapes are not interchangeable: `db.get_history()` and `db.get_user_history_tracks()` return **track** columns, while the profile's rows carry the **history** columns `completed`, `duration_listened`, `listening_measured`, `media_listened`, `session_finished`. `RecommendationService._profile(history)` (`services/recommendation_service.py:173–185`) *overwrites* `profile.recent_history` with the API-supplied rows (`merged[:50]`), which silently strips the measurement columns from the 50 newest rows — and the measured-skip demotion in `_rank_tracks` (`:256–266`) keys off exactly those columns.
- **Cause:** The taste profile was introduced as a service (`services/taste_profile.py`) while `core/database.py` kept its own aggregations, and the bridge passes history rows between the two layers without normalising the shape.
- **Trigger conditions:** Any home load (`get_feed`, `get_home_mixes`, `get_home_releases`, `get_popular_tracks`, `get_authentic_home_feed`).
- **User impact:** The home page is internally inconsistent: an artist can be in the "Исполнители" section (driven by `db.get_top_artists`, play-count only) and simultaneously absent from the recommendations and mixes (driven by the weighted, recency-decayed profile). The user sees their most-played artist listed as an artist they have never been recommended.
- **Evidence:**
  ```python
  # core/database.py:1708-1721
  SELECT artist, COUNT(*) as track_count, SUM(play_count) as total_plays, ... FROM tracks
  WHERE artist != 'Unknown Artist' GROUP BY artist ORDER BY total_plays DESC LIMIT ?
  # core/database.py:1784 (wrapped)
  GROUP BY LOWER(t.artist)
  # core/database.py:1616-1621 (get_history: one row per track)
  FROM history h JOIN tracks t ON h.track_id = t.id GROUP BY t.id ORDER BY played_at DESC LIMIT ?
  # core/database.py:1241-1245 (get_user_history_tracks: one row per EVENT)
  SELECT t.* FROM tracks t JOIN history h ON t.id = h.track_id ORDER BY h.played_at DESC LIMIT ?
  # services/taste_profile.py:143-153 (profile: 1500 rows, sliced to 50)
  ORDER BY h.played_at DESC LIMIT {HISTORY_LIMIT}   ->  self.recent_history = history_rows[:50]
  # services/recommendation_service.py:173-185 (the overwrite)
  profile.recent_history = merged[:50]
  ```
  The shape mismatch is directly observable: `db.get_history()` selects `t.title, t.artist, t.album, t.cover_path, t.cover_url, t.source, t.source_id` and `MAX(h.played_at)`, `COUNT(*)`, `COALESCE(SUM(h.duration_listened),0)` — it selects **none** of `h.completed`, `h.listening_measured`, `h.media_listened`, `h.session_finished`.
- **Reproduction / verification:** Compare the column lists of `core/database.py:1608–1623` and `core/database.py:1241–1245` with the history columns the profile selects at `services/taste_profile.py:139–141`. The correctness manifestation (the measured-skip demotion never firing for the 30–50 newest rows) is already recorded in the project register as **AUD-269**; this finding is the architectural root cause of the divergence, not a re-report of AUD-269.
- **Suggested fix:** One reader, one shape. Make `services/taste_profile.py` the only producer of "recently played" and "top artist" rows, expose a single `get_recent_history(limit)` / `get_top_artists(limit)` pair, and have `core/api.py` and `core/database.py`'s duplicated aggregations delegate to it (or delete the duplicates). The history row shape must be defined once and shared.
- **Fix side effects:** `get_home_artists` currently returns `db.get_top_artists()` rows (`artist`, `track_count`, `total_plays`, `play_count`, `plays`) that the UI renders; changing the source changes that payload (WN-31/32 file). `get_wrapped_stats` deliberately uses a different, period-scoped aggregation and should stay separate — it is a *report*, not a profile.
- **Discovered by:** B

---

#### F-WN-23-11  [P3] — The feed cache key is a 400 KiB `repr()` + SHA-256, rebuilt on every `_feed_tracks` call

- **File:** `services/recommendation_service.py:451–466`
- **Confirmed:** yes
- **Description:** `_feed_tracks` computes a cache key by building a tuple over **every known track** (recent + favourites + downloads + playlists + top tracks = up to ~6 000 rows), `repr()`-ing it into a multi-hundred-kilobyte string and hashing it:
  ```python
  seed_signature = tuple((self._content_key(t), t.get('id'), t.get('source'), t.get('source_id'),
                           t.get('file_path'), t.get('weighted_score'), t.get('is_favorite'),
                           t.get('is_downloaded'), t.get('duration_listened'), t.get('completed'),
                           t.get('media_listened'), t.get('session_finished'))
                          for t in self._known_tracks(profile))
  ...
  key = 'recommendation:feed:' + hashlib.sha256(repr(signature).encode('utf-8')).hexdigest()
  ```
- **Cause:** A cache key should be a compact digest of the *inputs*, not a serialisation of the entire profile.
- **Trigger conditions:** Every `_feed_tracks` call — i.e. every home load and every mix request.
- **User impact:** ~5 ms of pure CPU per call, plus ~400 KiB of transient allocation, on a heavy library. With `get_mixes` calling `_feed_tracks` once and `get_feed` once, that is ~10 ms per home load — small next to F-WN-23-2/3 but the same class of problem.
- **Evidence:**
  ```
  known tracks in the profile: 4570
    build seed_signature :     2.59 ms
    repr() size          :   402.6 KiB
    repr()               :     2.20 ms
    sha256               :     0.25 ms
    TOTAL per _feed_tracks call (this part alone):     5.04 ms
  ```
- **Reproduction / verification:** `_wn23b_measure_sig.py`.
- **Suggested fix:** Derive the key from a cheap monotone revision (e.g. the same settings/database revision used for the profile memo) plus the small, genuinely-varying parts (seed artists, top-artist scores, vibe key, date, feedback digest), rather than from every known track row.
- **Fix side effects:** The key must still change whenever the profile changes, otherwise a stale feed is served. Pairing it with the profile's revision counter (F-WN-23-2) is the natural implementation.
- **Discovered by:** B

---

#### F-WN-23-12  [P3] — The profile memo serialises two full deep-copies of the profile state under a single process-global lock

- **File:** `services/taste_profile.py:373–394` (+ `:26–27`)
- **Confirmed:** yes
- **Description:** `_cache_get` deep-copies the cached state while holding the module-global `_profile_cache_lock`:
  ```python
  with _profile_cache_lock:
      ...
      return copy.deepcopy(entry['state'])
  ```
  and `_cache_put` deep-copies again under the same lock:
  ```python
  state = copy.deepcopy({f: getattr(self, f) for f in self._STATE_FIELDS})
  with _profile_cache_lock:
      _profile_cache[cache_key] = {...}
  ```
  The state is up to 4 collections × `HISTORY_LIMIT` (1 500) rows plus `top_tracks` — roughly 6 000 dicts in the worst case.
- **Cause:** The lock is used both to protect the cache *map* and to guard the (expensive) copy of the cached value, so unrelated threads serialise behind the copy.
- **Trigger conditions:** Every profile build (two copies) and every cache hit (one copy).
- **User impact:** ~7 ms of lock-held time per copy (measured for a 6 000-row state) → ~14 ms serialised per build. With three builds per home load (F-WN-23-2), ~40 ms of globally-serialised work per home page load; on a busy machine this also delays any other thread that needs the lock.
- **Evidence:**
  ```
  === memo state deepcopy cost (module-global lock held during both copies) ===
    deepcopy of a 6000-row profile state: 6.81 ms per copy
    (one copy on cache GET, one on cache PUT, both under _profile_cache_lock)
  ```
  `_profile_cache` is a module-level global (`services/taste_profile.py:26–27`), so the lock is shared by every `UserTasteProfile` instance in the process.
- **Reproduction / verification:** `_wn23b_measure_alias2.py` (deepcopy block). The two `copy.deepcopy` calls are visible at `services/taste_profile.py:387` and `:390`.
- **Suggested fix:** Copy the state **outside** the lock (read the entry under the lock, release it, then `deepcopy` the snapshot), or store an immutable/serialised snapshot (e.g. a JSON blob) so the "copy" is a cheap `bytes` slice.
- **Fix side effects:** Copying outside the lock means the snapshot could be mutated by another thread between the lock release and the copy — the current code avoids that by copying under the lock. The immutable-snapshot variant (store the state pre-serialised) keeps the guarantee and removes the cost.
- **Discovered by:** B

---

### 3. Clean areas

Checked and found correct (brief):

- **No `core/` ↔ `services/` cycle in this area.** `services/recommendation_service.py` imports only `services.*` (`:18–22`); `services/taste_profile.py` imports only `services.artist_identity` + stdlib (`:17`); `core/services/recommendation.py` imports nothing from the app at all. The `core → services` direction is lazy and function-local (`core/app.py:223`, `core/api.py:2968, 2980, 3002, 3462`), so there is no import cycle introduced by WN-23. (A `core ↔ services` inversion exists elsewhere — `core/playback_recovery.py:9` → `services.music_matching` vs `services/soundcloud_service.py:774` → `core.playback_recovery` — but that is WN-18/WN-19's, not WN-23's.)
- **The candidate single-flight is correct.** `_collect_candidates` (`:330–364`) registers a `Future` in `_candidate_flights` under `_cache_lock`, followers wait with `future.result(timeout=12.0)`, and the leader pops the flight in a `finally`. The leader/follower split is exercised by `tests/test_recommendation_service.py:133–151`.
- **Caches are bounded.** `BaseMusicService._search_cache` is capped at 300 entries with a 300 s TTL and LRU eviction (`services/base_service.py:132–134, 243–270`); `_profile_cache` is capped at 4 entries (`services/taste_profile.py:341, 393–394`); `_candidate_flights` is popped in a `finally` (`:361–364`). No unbounded dictionary grows in this area.
- **`_candidate_executor` is shut down deterministically** by `core/app.py:579` during `AppCore.cleanup()`.
- **The profile build never writes to the database.** `build_from_db` only issues `SELECT`s; the history/favourite/download/playlist reads are wrapped in `try/except` with per-section degradation (`:154–155, 169–170, 186–187, 201–202, 218–219, 322–323`), so a schema mismatch produces a partial profile rather than an exception.
- **No raw SQL is issued against the recommendation path's own tables** — `services/taste_profile.py` uses only `PRAGMA`/`SELECT` through the connection handed to it; it does not reach into `db._write_lock` or the manager's internals. (Contrast with `services/smart_playlists.py` and `services/listening_comparison.py`, which do — those are WN-24/WN-25's.)
- **Offline mode is intercepted for every recommendation entry point** (`core/api.py:461–512`: `get_feed`, `get_popular_tracks`, `get_authentic_home_feed`, `get_home_releases`, `get_home_mixes`, `get_flow_tracks`, `get_recommendations`, `get_yt_playlist_tracks`, `get_track_wave`), so no provider is contacted offline.
- **`_emit` is not called from the recommendation path** — the service only invokes the `callback`/`error_callback` it was handed; the bridge owns the event emission.
- **The `_bounded_score` / duration sanitisation** (`:84–111, 227–233`) correctly clamps non-finite and negative values, and `tests/test_recommendation_service.py:200–203` pins it.
- **No secret or credential is written to the taste profile** — the profile carries only track metadata and derived scores; the Last.fm API key stays in settings and is never put in the cache key or payload.

---

### 4. Coverage gaps

- **The running app was never launched** (per the brief). All timings are from in-process harnesses against throwaway SQLite databases under `%TEMP%`; the real `~/.nedotify/nedotify_storage.db` was never opened, so the absolute numbers for a real user library are extrapolations from synthetic data (120–8 000 history rows, 50–1 000 favourites, 50–200 artist bindings).
- **`services/track_resolver.py` was not read in full.** `RecommendationService` delegates candidate resolution to it (`_collect_uncached_candidates:439`, `get_charts:588`, `get_smart_home_feed:738`); the cost of `resolve_tracks`/`resolve_track` inside the 12 s candidate budget is therefore an *assumption* in F-WN-23-9, not a measurement. Confirming it requires reading `services/track_resolver.py` (WN-18).
- **`services/youtube_service.py` / `services/soundcloud_service.py` were not read.** The measured provider latencies in F-WN-23-5/F-WN-23-9 come from stubs that raise immediately; the real 8 s `wait()` budget may be consumed mostly by `yt-dlp` rather than by the recommendation code.
- **The `emit` path was not exercised.** `AppApi._emit` (WN-03) was stubbed out in the home-load measurement, so the end-to-end latency of the home page (profile builds + provider fan-out + event emission) is not measured — only the Python-side portion.
- **The `~/.nedotify/cache/lastfm_cache.db` file was not inspected on disk** (the brief forbids touching `~/.nedotify/`). The claim that it survives `clear_storage` follows from the code paths (`utils/cache_manager.py:22–29` vs `services/lastfm_service.py:180–187`), not from an inspection of the real file.
- **Multi-process behaviour was not tested.** Only the single-process, multi-thread model was exercised.
- **The `tests/` suite was not executed** for this area. The statements about test coverage are based on reading the five named test files; a claim such as "no test pins the number of profile builds per home load" is a reading of the file list, not an execution result. `tests/test_recommendation_service.py:29–30` monkeypatches `RecommendationService._executor` with a 4-worker pool, so the cross-thread memo behaviour *is* exercised incidentally by the existing suite — but nothing asserts on it.
- **`core/api.py::get_authentic_home_feed` reachability** was confirmed by grepping `ui/web_new_v2/**` only; a dynamic call (`window.pywebview.api[method]`) would not have been found.
- **`tools/bench/`** was not run. The repo's own bench harness (`tools/bench/`) contains prior snapshots of `services/recommendation_service.py` / `services/taste_profile.py` hashes (`tools/bench/results/*.json`) which show those two files changed between the 2026-10-04 and 2026-10-15 runs, but the harness's own recommendation scenarios were not reproduced.

---

### 5. Architecture improvements (ARCH)

These are **not** defects — they are structural improvements. They are listed separately from section 2 as required.

#### ARCH-1 — The scoring core has two homes, and the wrong one is under `core/`

The live scoring core is `services/recommendation_service.py` (917 lines): candidate collection, ranking, seeding, mixes, feeds, waves. The second implementation is `core/services/recommendation.py` (240 lines, unreachable, different model — see F-WN-23-1). The `core/` directory is the *application shell* (`core/api.py` = the bridge, `core/app.py` = wiring, `core/database.py` = persistence, `core/proxy.py` = transport); it holds no business logic of its own except inside `DatabaseManager`. Placing a feature-scoring engine there is a layering inversion: the engine depends on nothing, so it cannot be tested against the real data model, and nothing keeps it honest.

**Where the scoring core should live:** `services/`, next to the providers it consumes — which is where it already is. The concrete change is to delete `core/services/recommendation.py` and, if `core/services/` exists only for it, remove the directory. The *scoring* half of `services/recommendation_service.py` (`_calculate_taste_weights`, `_rank_tracks`, `_seed_tracks`, `_get_merged_seed_artists`, `_feedback`) is pure, provider-independent and directly unit-testable; the *collection* half (`_collect_uncached_candidates`, `_get_merged_seed_artists`'s Last.fm branch, `get_charts`, `get_smart_home_feed`) is provider-bound. Splitting the class into `services/recommendation_scorer.py` (pure) and `services/recommendation_service.py` (I/O) would make the scoring core testable without stubbing four providers, and would let the cache keys and the profile memo live on one side.

#### ARCH-2 — Every place that reads the listening history and builds a profile

Complete enumeration of the producers of "what the user listens to" in the desktop product:

| # | Site | Reads | Builds a profile? | Reaches the UI? |
|---|---|---|---|---|
| 1 | `services/recommendation_service.py:173–185` `_profile()` | `UserTasteProfile.build_from_db(db)` (settings-aware) | Yes | Yes (feed, mixes, releases, wave, flow) |
| 2 | `services/recommendation_service.py:651` `get_custom_artists` | `UserTasteProfile().build_from_db(db)` (**no settings**) | Yes | No caller |
| 3 | `services/recommendation_service.py:723` `get_smart_home_feed` | `UserTasteProfile().build_from_db(db)` (**no settings**) | Yes | No caller (via `get_authentic_home`) |
| 4 | `core/api.py:3340–3343` `get_authentic_home_feed` | `db.get_user_history_tracks(limit)` | No | No UI caller |
| 5 | `core/api.py:3742` `get_feed` | `db.get_history(limit=30)` | No (fed into #1) | Yes |
| 6 | `core/api.py:3784` `get_home_mixes` | `db.get_history(limit=30)` | No (fed into #1) | Yes |
| 7 | `core/api.py:3323` `get_popular_tracks` | `db.get_history(limit=10)` (as a fallback payload only) | No | Yes |
| 8 | `core/api.py:3396` `get_profile_stats` | `db.get_history(limit=5)` | No | Yes (profile page) |
| 9 | `core/api.py:3761` `get_home_artists` | `db.get_top_artists(limit)` | No (a *different* aggregation) | Yes |
| 10 | `core/api.py:3770` `get_home_releases` | `db.get_top_artists(limit=5)` | No (a *different* aggregation) | Yes |
| 11 | `services/recommendation_service.py:604` charts fallback | `db.get_most_played_tracks(limit)` | No (a *different* aggregation) | Yes |
| 12 | `core/database.py:1569–1584` `get_recommendation_quality` | `history` grouped by `recommendation_context` | No | Via `core/api.py:3021` |
| 13 | `core/database.py:1723–1834` `get_wrapped_stats` | `history` ⋈ `tracks`, grouped by `LOWER(t.artist)` | No (a report) | Via `core/api.py:3156` |
| 14 | `core/database.py:1836–1860` `get_analytics_summary` | `history` ⋈ `tracks` (full scan) | No | Yes |

Three of these (#9, #10, #11) are *alternative* "top artist" definitions living in `core/database.py` that duplicate — and disagree with — the taste profile's. **Direction:** converge on #1 as the single producer; move the "top artist" aggregation into `services/taste_profile.py` and have `core/database.py` stop exporting its own.

#### ARCH-3 — The recommendation path is the only consumer that touches the DB through a *service* rather than the manager's API

`services/taste_profile.py` reaches into the connection directly (`_get_conn` at `:523–533` accepts a `DatabaseManager`, a raw `sqlite3.Connection` **or a path string**, and opens its own connection in the last case). This gives it three back-ends and forces it to re-implement schema detection (`_detect_schema`, `:406–422`) — a 40-line re-implementation of what `core/database.py` already knows. It also means the profile is the only reader that must handle "the DB may be an older schema".

**Direction:** let `DatabaseManager` expose a single `read_taste_signals()` (or a small query object) that returns the four signal sets with a documented row shape, and let `services/taste_profile.py` become a pure function over that result. The profile's schema-detection code and its three-way connection handling then disappear, and the row shape is defined once (which is the root cause of F-WN-23-10).

#### ARCH-4 — The bridge calls the recommendation service through six different conventions

`core/api.py` calls `self._core.recommendations` in six shapes: `get_feed(history, max_results=…, callback=…, error_callback=…)` (`:3378`), `get_releases(artists, max_results=…, callback=…, error_callback=…)` (`:3772`), `get_mixes(history, max_results=…, callback=…, error_callback=…)` (`:3786`), `get_wave_for_track(track, limit=…, exclude_ids=…, callback=…, error_callback=…)` (`:3573`), `get_flow_tracks_sync(track, limit=…, exclude_ids=…)` (`:4119`, **synchronous**) and `get_charts(region, callback=…)` (`:3327`, **no error callback**). `get_charts` is the only one that cannot report failure at all — it falls back to the local DB and to `CURATED_WELCOME_TRACKS` inside the service, so the bridge can never tell the difference.

**Direction:** one convention — every entry point takes a callback *and* an error callback, and every one of them returns promptly. That would have made F-WN-23-9 (the synchronous `get_flow_tracks`) and F-WN-23-5 (the discarded error text) structurally impossible.

#### ARCH-5 — The alias table, the profile memo and the feed cache key are all "derived from settings/DB" values that are recomputed instead of versioned

Three separate derived values in this area are recomputed rather than memoised against a revision: the alias table (F-WN-23-3), the profile memo (F-WN-23-2) and the feed cache key (F-WN-23-11). Each is a "versioned cache" waiting to happen.

**Direction:** give `SettingsManager` a monotone `revision` counter bumped on every `set()`, and give `DatabaseManager` an equivalent `data_revision` (it already has `PRAGMA data_version` and `conn.total_changes`). Then: the alias table is keyed by `settings.revision`; the profile memo is keyed by `(db.data_revision, settings.revision)`; the feed cache key is a digest of `(profile revision, seed artists, vibe, date, feedback digest)`. This single change removes two of the four findings in this report and makes the memo actually hit.
