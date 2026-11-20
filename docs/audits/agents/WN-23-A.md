## AREA WN-23 — Recommendations & taste profile — ROLE A

### 1. Scope reviewed

**Files opened (path: line ranges actually read):**

- `services/recommendation_service.py` — L1–917 (full file, 827 non-empty lines)
  - `RecommendationService` L38–917; `_profile` L173; `_seed_tracks` L191; `_calculate_taste_weights` L209;
    `_bounded_score` L227; `_rank_tracks` L235; `_collect_candidates` L330; `_collect_uncached_candidates` L366;
    `_feed_tracks` L451; `_async_recommendation` L481; `_get_merged_seed_artists` L495; `get_charts` L568;
    `get_feed` L626; `get_releases` L676; `get_mixes` L691; `get_smart_home_feed` L719; `get_wave_for_track` L901;
    `get_flow_tracks_sync` L916.
- `services/taste_profile.py` — L1–634 (full file, 563 non-empty lines)
  - `UserTasteProfile` L30–634; `build_from_db` L60–337; cache block L339–404; `_detect_schema` L406;
    `_get_artist` L545; `_listening_weight` L556; `_recency_factor` L579; `_parse_dt` L588; `_parse_time_slot` L611.
- `core/services/recommendation.py` — L1–240 (full file, 189 non-empty lines)
  - `RecommendationEngine` L22–184; `run_recommendation` L187; `build_real_engine` L192–240.
- Callers traced (read, not owned by WN-23):
  - `core/api.py` — L470–512 (offline interception), L1240–1439 (`_persist_listening` L1290, `maybe_log_history` L1304,
    `report_listening_state` L1332, `report_state` L1355), L2077–2186 (`search`, shape comparison),
    L2967–3030 (`get_recommendation_feedback` L2967, `set_recommendation_feedback` L2979,
    `get_recommendation_quality` L3021), L3300–3409 (`get_popular_tracks` L3315, `get_authentic_home_feed` L3337),
    L3430–3479 (`_store_artist_binding` L3461), L3520–3639 (`get_recommendations` L3537, `get_track_wave` L3555),
    L3730–3819 (`get_feed` L3740, `get_home_releases` L3765, `get_home_mixes` L3782), L4080–4149 (`get_flow_tracks` L4110).
  - `core/app.py` — L85–244 (lazy `recommendations` property L213–234), L565–586 (pool shutdown).
  - `core/database.py` — L100–225 (schema; `_get_connection` L179–205 thread-local), L1184–1262
    (`get_all_tracks` L1184, `get_favorite_tracks` L1224, `get_user_history_tracks` L1239),
    L1300–1419 (`record_listening_once` L1320), L1550–1629 (`begin_listening_session` L1558,
    `get_recommendation_quality` L1569, `update_history_duration` L1586, `get_history` L1599).
  - `core/settings.py` — L160–189 (personalization defaults), L345–454 (`get` L351, `set` L401).
  - `services/base_service.py` — L65–329 (`_SharedExecutor`, `_join_request` L140, `get/set_search_cache` L243–276).
  - `services/artist_identity.py` — L1–63 (`name_key`, `artist_aliases`, `canonical_artist`, `track_key`).
  - `services/track_resolver.py` — L1–476 (memo, `resolve_tracks` L362, `prefetch` L435).
  - `services/lastfm_service.py` — L92–200 (`_resolve_api_keys` L134, `_api_request` L309), L300–459.
  - `ui/web_new_v2/js/home.js` L177–200, `js/player.js` L1520–1580, `js/utils.js` L1084–1103 (read-only, for call-site facts).
  - `tests/test_recommendation_service.py`, `tests/test_taste_profile.py` (existing coverage).

**Callees traced into other areas (root cause lives there, not here):**

- `core/api.py::get_recommendations` L3550 — the hard-coded `evt.wait(timeout=3.0)` that truncates the
  recommendation result (bridge/timeout concern → **WN-09**, cross-referenced in F-WN-23-4).
- `core/api.py::get_flow_tracks` L4110 — synchronous bridge call that runs the whole recommendation
  computation on the bridge thread (bridge-blocking concern → **WN-10**).
- `core/database.py::record_listening_once` L1320 — deprecated `raise NotImplementedError`; the live dedup is
  `AppApi.maybe_log_history` / `_persist_listening` (**WN-05**).
- `core/database.py::_get_connection` L179 — per-thread SQLite connections (the trigger for F-WN-23-3) (**WN-12**).
- `services/track_resolver.py` memo/timeout behaviour (resolution latency, **WN-18**).
- `services/lastfm_service.py` request timeouts and key rotation (**WN-21**).

---

### 2. Findings

#### F-WN-23-1  [P2] — `core/services/recommendation.py` is an orphan module: the "scoring core" is never executed, and two personalization settings are inert because of it

- **File:** `core/services/recommendation.py:1-240` (whole file); `services/recommendation_service.py:209-233` (the scoring that *is* live); `core/settings.py:166-176`
- **Confirmed:** yes
- **Description:** The area map lists `core/services/recommendation.py` as "recommendation scoring core". Nothing in the
  desktop product imports it. `RecommendationEngine`, `run_recommendation()` and `build_real_engine()` have zero
  importers; the live ranking is `RecommendationService._calculate_taste_weights` / `_rank_tracks` in
  `services/recommendation_service.py`. Consequently `personalization.explicit_artists` and
  `personalization.preferred_moods` (both declared in `core/settings.py:168-169`) are read **only** by the dead
  module and have no effect on any recommendation the user ever sees.
- **Cause:** The module was written against a different data model (`tracks` rows carrying `artist_id`,
  `is_new_release`, `bpm`, `energy`, `mood`, `acoustics`, `bass`, `global_streams`, `viral_velocity`) that the SQLite
  schema in `core/database.py:213-239` does not have. Even if it were wired in, `release_pool` and
  `artist_radio` would always be empty and the charts would all be zero-sorted.
- **Trigger conditions:** Always. The file is simply never loaded.
- **User impact:** (a) Two documented personalization knobs (`explicit_artists`, `preferred_moods`) do nothing;
  (b) the code that a maintainer would read as "the scoring core" is not the code that ranks anything, so fixes
  applied there are silently inert; (c) the module carries latent crashes that will fire the moment somebody wires
  it in.
- **Evidence:**
  - Repo-wide grep (excluding `android/`), the only hits are the module's own definitions:
    ```
    core/services/recommendation.py:187: def run_recommendation(user_profile: Dict, current_context: Dict, catalog: List[Dict]) -> Dict:
    core/services/recommendation.py:192: def build_real_engine(db, personalization: dict) -> RecommendationEngine:
    ```
    (`core/app.py:223` imports `services.recommendation_service`, a different module.)
  - `core/services/recommendation.py:27` — `self.catalog_map = {t["id"]: t for t in catalog}` → `KeyError: 'id'`
    for any catalog row without an `id` key (probe output: `raised: KeyError 'id'`).
  - `core/services/recommendation.py:112` — `release_pool = [t for t in eligible if t.get("is_new_release") and t.get("artist_id") in self.subs_set]`;
    `core/services/recommendation.py:134-138` — `radio_artist = self.subs_set.copy().pop()` then
    `[t for t in eligible if t.get("artist_id") == radio_artist]`. The `tracks` table has no `artist_id` and no
    `is_new_release` column (`core/database.py:213-239`), so both are permanently empty.
  - `core/services/recommendation.py:149-150` — `global_streams` / `viral_velocity` do not exist in the schema → both
    chart lists are sorted by a constant 0.
- **Reproduction / verification:**
  ```
  Get-ChildItem -Recurse -Include *.py -File | Where-Object { $_.FullName -notmatch '\\android\\' } |
    Select-String -Pattern 'services\.recommendation|run_recommendation|build_real_engine'
  ```
  → only the definitions inside `core/services/recommendation.py` itself.
  Probe (`wn23_probe2.py`):
  ```
  RecommendationEngine({...}, {"activity":"chill"}, [{"title":"x","artist":"y"}])
  → raised: KeyError 'id'
  ```
- **Suggested fix:** Either delete `core/services/recommendation.py` (and the two now-inert settings keys), or make it
  the single scoring implementation and delete the duplicated scoring in `RecommendationService`. Do not leave two
  parallel scorers.
- **Fix side effects:** Deleting the module removes the only reader of `explicit_artists` / `preferred_moods`; if those
  are meant to work, they need a real implementation in `RecommendationService._calculate_taste_weights` first.
  Wiring the module in as-is would introduce the `KeyError` above plus two permanently-empty sections.
- **Discovered by:** A

---

#### F-WN-23-2  [P2] — The API-supplied history shadows the profile's measured rows, so the measured-skip demotion never fires in production

- **File:** `services/recommendation_service.py:173-185` (`_profile` merge), `services/recommendation_service.py:255-266` (skip detection), `core/api.py:3740-3748`, `core/api.py:3782-3794`, `core/api.py:3337-3380`
- **Confirmed:** yes (reproduced end-to-end against a real `DatabaseManager`)
- **Description:** `UserTasteProfile.build_from_db` produces `recent_history` rows that carry the measured-listening
  columns (`completed`, `listening_measured`, `media_listened`, `session_finished`, `duration`). `_rank_tracks` uses
  exactly those columns to build its `skipped` set and to apply the `score -= 1` demotion. But `RecommendationService._profile()`
  merges a caller-supplied `history` list **in front of** the profile rows and dedupes by content key, so the first
  row for a track wins. Every production caller passes such a history, and those rows lack the measured columns:
  `db.get_history()` returns `track_id, played_at, play_count, duration_listened, t.title…` (no `duration`,
  no `completed`, no `listening_measured`), and `db.get_user_history_tracks()` returns `t.*` (no history columns at all).
  The result: the demotion that is supposed to stop the app from re-serving a track the user skipped is dead in the
  real feed, in exactly the tracks most likely to be re-served (the most recent ones).
- **Cause:** The merge is "first writer wins" on content key, and the caller's aggregate row is not a superset of the
  profile's measured row. The skip detector needs `duration` **and** `duration_listened` **and** `completed` together;
  the aggregate row only has `duration_listened`.
- **Trigger conditions:** Any feed/mixes request that carries a non-empty history — i.e. always, once the user has
  played anything. `ui/web_new_v2/js/home.js:182` calls `get_feed` and `home.js:192` calls `get_home_mixes`, both of
  which pass `db.get_history(limit=30)`.
- **User impact:** The "I skipped this, don't show it again" behaviour silently does nothing on the home page. A track
  the user bounced off in the first seconds is re-served as a top recommendation.
- **Evidence:**
  - `services/recommendation_service.py:173-185`:
    ```python
    def _profile(self, history=None):
        profile = UserTasteProfile(settings=self.settings).build_from_db(self.db) if self.db else UserTasteProfile(settings=self.settings)
        if history:
            merged, seen = [], set()
            for track in list(history) + profile.recent_history:
                if not isinstance(track, dict) or not track.get('title'):
                    continue
                key = self._content_key(track)
                if key not in seen:
                    seen.add(key)
                    merged.append(track)
            profile.recent_history = merged[:50]
        return profile
    ```
  - `services/recommendation_service.py:260-264` (the demotion input):
    ```python
    if listened is not None and duration and not track.get('completed') and not track.get('is_favorite'):
        try:
            heard = float(track.get('media_listened') or listened)
            if 0 <= float(listened) < 10 and heard < float(duration) * .1 and (...):
                skipped.add(self._content_key(track))
    ```
    `duration` is `None` on the aggregate row → the branch is never entered.
  - `core/api.py:3742` — `history = self._core.db.get_history(limit=30) or []`, then
    `core/api.py:3744-3748` — `self._core.recommendations.get_feed(history, max_results=max_results, …)`.
- **Reproduction / verification:** probe `wn23_probe3.py` (real `DatabaseManager`, a track with
  `begin_listening_session` + `update_history_duration(2.0, completed=False, media_listened=2.0, session_finished=True)`):
  ```
  === 1. profile built directly from the DB (no API history) ===
  top-1 with a measured skip present: ['Brand New']
  === 2. profile merged with the API history (core/api.py::get_feed path) ===
  api history row keys: ['album','artist','cover_path','cover_url','duration_listened','play_count',
                          'played_at','source','source_id','title','track_id']
  merged recent_history[0] keys: [ ... same aggregate shape ... ]
  top-1 after the API merge: ['Skipped Song']      <-- demotion lost
  ```
  The existing unit test `tests/test_recommendation_service.py:93-98` passes only because it builds the profile
  without an API history.
- **Suggested fix:** Merge the measured fields instead of replacing the row — e.g. keep the profile's measured row for
  a content key and copy the caller's aggregate fields onto it (or merge `history` *after* the profile rows and only
  append keys the profile does not know).
- **Fix side effects:** The merged list would grow (measured rows carry more columns); `_rank_tracks` reads
  `profile.recent_history` for skip detection only, so widening it is low-risk. Any change to merge order also changes
  `recent_history[:1]`, which is what `_feed_tracks` excludes — see F-WN-23-5.
- **Discovered by:** A

---

#### F-WN-23-3  [P2] — The 60 s taste-profile memo can never hit across threads, because the cache revision embeds the thread-local SQLite connection

- **File:** `services/taste_profile.py:357-371` (`_connection_revision`), `services/taste_profile.py:373-394` (`_cache_get`/`_cache_put`), `services/taste_profile.py:22-24` (`PROFILE_CACHE_TTL`); `core/database.py:179-205` (`_get_connection` → thread-local)
- **Confirmed:** yes (measured)
- **Description:** `DatabaseManager.conn` returns a **per-thread** `sqlite3.Connection` (`self._local.connection`).
  `UserTasteProfile._connection_revision(conn)` returns the tuple `(conn, conn.total_changes, data_version, schema_version)`
  — i.e. the connection **object** is part of the revision. The cached profile is stored under a key that does *not*
  contain the connection (`(id(db), aliases)`), and `_cache_get` compares `entry['revision'] != revision`. Two
  different threads therefore always produce different revisions, so the 60 s memo is a miss on every call that lands
  on a different thread — which is the normal case, because the recommendation service runs on the shared 8-worker
  pool (`BaseMusicService._executor`) while the UI calls arrive on bridge threads.
  The invalidation logic itself is sound (writes from other connections bump `PRAGMA data_version`); only the
  *memoisation* is defeated.
- **Cause:** A per-connection identity was used as a proxy for "same data source", but the connection is
  thread-scoped, so the proxy is thread-scoped too.
- **Trigger conditions:** Any two profile builds on different threads. With `RecommendationService._executor` having
  8 workers and the UI triggering feed / mixes / releases / wave requests, this is the common path.
- **User impact:** The stated intent ("Recomputing the same profile several times per second is pure waste") is not
  met: every request re-runs 5 queries (history JOIN, favourites, downloads, playlist tracks, played_at) with
  `LIMIT 1500` each and re-`deepcopy`s the whole profile state into the cache while holding the module-global
  `_profile_cache_lock`. Measured cost on an 800-track / 200-favourite library: ~11 ms and 7 SELECTs per call instead
  of 0.001 s. On a large library (1500 history rows, 1500 favourites) this grows; the deepcopy is taken under the
  global lock, so concurrent recommendation requests serialise on it.
- **Evidence:**
  - `services/taste_profile.py:365-368`:
    ```python
    data_version = conn.execute('PRAGMA data_version').fetchone()[0]
    schema_version = conn.execute('PRAGMA schema_version').fetchone()[0]
    return (conn, conn.total_changes, data_version, schema_version)
    ```
  - `core/database.py:179-201` — `_get_connection()` stores the connection in `self._local.connection`
    (`self._local = threading.local()`, `core/database.py:155`), so every thread gets its own connection object.
  - `services/taste_profile.py:385` — `if entry.get('revision') != revision: return None` (tuple compare → the
    connection element is compared by identity).
- **Reproduction / verification:** probe `wn23_probe.py`:
  ```
  === A. profile cache hit inside one thread ===
  same-thread SELECT count on 2nd build: 0
  === B. profile cache across threads ===
  thread results: {'t1': {'selects': 7, 'conn_id': 1775225578464},
                   't2': {'selects': 7, 'conn_id': 1775225578704}}
  main thread conn id: 1775225577744
  ```
  and probe `wn23_probe4.py` (800 tracks):
  ```
  per-thread rebuild times: ['0.012s', '0.011s', '0.011s', '0.013s']
  ```
  The same probe also confirms the *invalidation* half is correct:
  ```
  === C. does a write from another thread invalidate the cache? ===
  before: ['Artist']
  after external write: ['The Weeknd', 'Dua Lipa', ...]      <-- invalidated, correct
  ```
- **Suggested fix:** Drop the connection object from the revision tuple (keep `data_version` + `schema_version` +
  a DB-level change counter), or key the memo by connection identity so each thread gets its own entry.
- **Fix side effects:** Removing `conn` from the revision means the revision no longer distinguishes two different
  databases that happen to share a `data_version`; the cache key already contains `id(db)` / the DB path, so the
  risk is contained. Keeping `conn.total_changes` is harmless but must not be the only signal.
- **Discovered by:** A

---

#### F-WN-23-4  [P2] — `AppApi.get_recommendations` returns an empty list whenever the recommendation takes longer than 3 s, and the late result is thrown away

- **File:** `core/api.py:3537-3553` (caller), `services/recommendation_service.py:552-566` (`get_recommendations` / `_fetch_recommendations`), `services/recommendation_service.py:901-914` (`get_wave_for_track`)
- **Confirmed:** yes (reproduced with a slow provider)
- **Description:** `AppApi.get_recommendations` submits the work and then waits at most 3.0 s for the callback. The
  work itself (`get_wave_for_track` → `_collect_candidates` → provider fan-out + metadata resolution) is bounded at
  ~12 s, so in the normal case the wait expires, the method returns `[]`, and the real result arrives afterwards into
  a `res` list that the function has already returned. The recommendation work is still performed (network, DB,
  threads) and its result is discarded.
- **Cause:** A synchronous bridge method with a hard timeout that is much shorter than the callee's own deadline, and
  with no fallback/caching of the late result.
- **Trigger conditions:** Any cold or slow provider response (>3 s). The candidate deadline in
  `_collect_uncached_candidates` is `time.monotonic() + 12.0` (`services/recommendation_service.py:367`), and the
  provider wait alone is up to 8 s (L389).
- **User impact:** The bridge method silently returns "no recommendations" on every cold call; the background work is
  wasted. Currently no UI caller exists (`ui/web_new_v2/js/*` uses `get_track_wave` / `get_flow_tracks` instead), so
  the impact is latent — but the method is part of the public ~200-method bridge surface.
- **Evidence:**
  - `core/api.py:3545-3553`:
    ```python
    self._core.recommendations.get_recommendations(
        track_data, max_results=max_results, callback=callback,
        error_callback=lambda _error: evt.set(),
    )
    evt.wait(timeout=3.0)
    …
    return res[:max_results]
    ```
  - `services/recommendation_service.py:552-566`: `get_recommendations` submits `_task` to the shared pool;
    `_fetch_recommendations` → `self.get_wave_for_track(seed_track, limit=max_results)` — called **without** a
    callback, so `get_wave_for_track` returns `task()` synchronously (`services/recommendation_service.py:911-914`),
    i.e. the whole fan-out runs before the callback fires.
- **Reproduction / verification:** probe `wn23_probe2.py` with a provider that sleeps 5 s:
  ```
  after 3.0s wait, result present? False elapsed 3.00s
  late callback delivered: True titles: ['Slow Result']
  total elapsed 5.00s
  ```
- **Suggested fix:** Either make the bridge method asynchronous (emit an event like `get_track_wave` does) or raise the
  wait to at least the callee's own deadline. The 3.0 s constant itself is bridge code → **WN-09** owns that half; the
  WN-23 half is that `RecommendationService` offers no synchronous/bounded-to-3 s path.
- **Fix side effects:** Raising the timeout to ~12 s would hold the pywebview bridge call open for 12 s (pywebview
  dispatches API calls off the UI thread, but the JS promise stalls). The event-based shape already used by
  `get_track_wave` (`core/api.py:3555-3581`) is the lower-risk option.
- **Discovered by:** A

---

#### F-WN-23-5  [P3] — Only the single newest play is excluded from the feed; the 2nd…50th most recent track can be re-served

- **File:** `services/recommendation_service.py:471-473` (`_feed_tracks`), `services/taste_profile.py:143-153` (the profile history is one row per listening *event*, so it holds several rows for the same track)
- **Confirmed:** yes
- **Description:** `_feed_tracks` excludes exactly one track: `exclude_tracks=profile.recent_history[:1]`. Everything else
  the user played recently is re-added as a candidate (`familiar = … + profile.recent_history`) and can be ranked back
  into the feed. The only mechanism that would demote them is the measured-skip demotion, which is dead in production
  (F-WN-23-2).
- **Cause:** The exclusion is a slice of one element rather than a window, and the demotion path that covered the rest
  is broken.
- **Trigger conditions:** A user with more than one recent play; typical after a few minutes of listening.
- **User impact:** The home feed can show tracks the user just heard, which reads as a loop/"the app is ignoring me".
- **Evidence:** `services/recommendation_service.py:471-473`:
  ```python
  familiar = profile.get_seed_tracks(limit=20) + profile.get_local_liked_and_downloaded_tracks(limit=20) + profile.recent_history
  tracks = self._rank_tracks(candidates + familiar, profile, max_results,
                             exclude_tracks=profile.recent_history[:1])
  ```
- **Reproduction / verification:** probe `wn23_probe2.py`:
  ```
  === F. can the feed return a recently played (not the very last) track? ===
  feed ranking contains 'Older Two': True
  titles: ['Older Two', 'Brand New']
  ```
  (`recent_history = [Recent One, Older Two]`, `exclude_tracks=recent_history[:1]`.)
- **Suggested fix:** Exclude a recency window (e.g. the last N plays / the last X minutes) rather than one element, or
  demote anything present in `recent_history` below the discovery floor.
- **Fix side effects:** Excluding more history reduces the "familiar" pool that the feed intentionally mixes in
  (`familiar_cap = max(1, round(limit * 0.3))`); with a small library the feed could get shorter. The empty-profile
  fallback (`CURATED_WELCOME_TRACKS`) only triggers when the profile is empty, so a heavy exclusion could starve the feed.
- **Discovered by:** A

---

#### F-WN-23-6  [P3] — The blocked-artist / disliked-track feedback is not applied on the "popular tracks" path

- **File:** `services/recommendation_service.py:568-624` (`get_charts`), `core/api.py:3315-3335` (`get_popular_tracks`)
- **Confirmed:** yes
- **Description:** `RecommendationService._feedback()` (blocked artists + disliked tracks, read from
  `personalization.blocked_artists` / `personalization.disliked_tracks`) is consulted in `_seed_tracks`,
  `_collect_candidates` and `_rank_tracks` — but **not** in `get_charts`. The home page's "Популярное" section is
  served by `get_popular_tracks` → `RecommendationService.get_charts`, so a user who explicitly blocked an artist still
  sees that artist's tracks in the popular section.
- **Cause:** The exclusion is implemented per call site instead of as a filter applied to every user-facing track list.
- **Trigger conditions:** The user blocks an artist/track (via `ui/web_new_v2/js/utils.js:1084-1103` →
  `core/api.py:2979`) and then opens the home page.
- **User impact:** A blocked artist reappears in one of the four home sections, which reads as "the block did not work".
- **Evidence:** `services/recommendation_service.py:568-624` — `get_charts` contains no call to `self._feedback()`;
  contrast with `services/recommendation_service.py:241-242`:
  ```python
  blocked, disliked = self._feedback()
  excluded_content.update(disliked)
  ```
  `core/api.py:3325-3327`:
  ```python
  provider = getattr(self._core.recommendations, "get_charts", None)
  if provider:
      provider(region, callback=lambda tracks: self._emit("popular_results", tracks or []))
  ```
- **Reproduction / verification:** static — `get_charts` (L568-624) never calls `_feedback()`; `_feedback()` is called at
  L193, L241, L333, L533 only.
- **Suggested fix:** Apply `blocked`/`disliked` to the chart result set as well (and, ideally, in one shared
  "finalise user-facing tracks" filter).
- **Fix side effects:** A global chart section would lose blocked artists — that is the intended semantics of
  "exclude from recommendations", but it should be a deliberate decision, since a *global* chart is arguably not a
  personal recommendation.
- **Discovered by:** A

---

#### F-WN-23-7  [P3] — Single-flight candidate collection: the follower's 12 s timeout races the leader's ~12 s deadline, so two concurrent identical requests can get different answers

- **File:** `services/recommendation_service.py:330-364` (`_collect_candidates`), `services/recommendation_service.py:366-449` (`_collect_uncached_candidates`)
- **Confirmed:** yes (code-path analysis; timing reproduced for the equivalent wait in F-WN-23-4)
- **Description:** The leader of a candidate flight runs `_collect_uncached_candidates`, whose own deadline is
  `time.monotonic() + 12.0`; the provider wait is capped at 8 s and the metadata resolution then gets whatever is left
  of the 12 s budget. A follower that joins the same flight waits `future.result(timeout=12.0)` — the same 12 s. When
  the providers are slow the leader finishes at ≈12 s, so the follower is a coin-flip between receiving the result and
  timing out with `return []`. A follower also re-raises the leader's exception verbatim.
- **Cause:** The follower's timeout is equal to (not greater than) the leader's internal deadline, so there is no margin
  for the hand-off.
- **Trigger conditions:** Two concurrent requests for the same seed set while the providers take >8 s. The UI can
  produce this (home feed + mixes + wave requested close together).
- **User impact:** One of the two concurrent callers silently receives an empty feed/mix list while the other gets a
  full one; the empty one is what the user sees for that section.
- **Evidence:**
  - `services/recommendation_service.py:347-351`:
    ```python
    if not leader:
        try:
            return [dict(t) for t in future.result(timeout=12.0)]
        except TimeoutError:
            return []
    ```
  - `services/recommendation_service.py:367` — `deadline = time.monotonic() + 12.0`;
    `services/recommendation_service.py:389` — `wait(futures, timeout=min(8.0, max(0, deadline - time.monotonic())))`;
    `services/recommendation_service.py:435-439` — `remaining = max(0, deadline - time.monotonic())` →
    `self.resolver.resolve_tracks(pairs, timeout=remaining)`.
- **Reproduction / verification:** Deterministic by construction: the leader's worst case equals the follower's
  timeout. A deterministic test can be written by monkeypatching `_collect_uncached_candidates` to sleep 12.05 s and
  asserting that the follower returns `[]` while the leader returns candidates.
- **Suggested fix:** Give the follower a margin (e.g. `timeout=deadline + 2 s`), or have the follower reuse the
  leader's result through the search cache rather than a bare future.
- **Fix side effects:** A longer follower timeout keeps the caller thread waiting longer in the slow case; the
  single-flight purpose (avoid duplicate provider work) argues for waiting rather than returning early.
- **Discovered by:** A

---

#### F-WN-23-8  [P3] — `get_smart_home_feed` calls Last.fm unconditionally, with no key check and no overall deadline (up to ~5 sequential 5 s HTTP calls + per-section resolution prefetches)

- **File:** `services/recommendation_service.py:719-866` (`get_smart_home_feed`), contrast `services/recommendation_service.py:382` (`if self._lastfm_enabled():`)
- **Confirmed:** yes
- **Description:** Every other Last.fm consumer in this file guards the call with `_lastfm_enabled()`.
  `get_smart_home_feed` does not: it calls `self.lastfm.artist.getTopTracks(...)` four times and
  `self.lastfm.chart.getTopTracks(...)` twice, sequentially, each with a 5 s HTTP timeout
  (`services/lastfm_service.py:330`), plus a `_prefetch_resolutions` batch per section (each bounded by
  `TrackResolver.BATCH_TIMEOUT = 10 s`). There is no overall deadline for the task. With a configured API key and a
  slow Last.fm, one task can occupy a shared worker for a minute.
  Note: without a key, `_api_request` short-circuits (`services/lastfm_service.py:315-318`) so no network is used.
- **Cause:** The `_lastfm_enabled()` guard was applied to the candidate fan-out but not to the home-feed builder.
- **Trigger conditions:** Last.fm configured (`auth.lastfm_api_key` / `LASTFM_API_KEY`) and slow or rate-limited.
- **User impact:** The home feed is late or empty. Currently latent: `get_smart_home_feed` is reached only through
  `get_authentic_home`, which no UI code calls (`ui/web_new_v2/js/home.js:177-192` uses `get_popular_tracks`,
  `get_feed`, `get_home_releases`, `get_home_mixes` instead).
- **Evidence:** `services/recommendation_service.py:756` — `top_trks = self.lastfm.artist.getTopTracks(artist, limit=5)`
  with no `_lastfm_enabled()` check nearby; `services/recommendation_service.py:765` — `chart_trks = self.lastfm.chart.getTopTracks(limit=8)`;
  `services/recommendation_service.py:845` — `chart_raw = self.lastfm.chart.getTopTracks(limit=15)`.
  The only exception handler is the outer `except Exception as e:` at L861, which aborts the whole feed.
- **Reproduction / verification:** static — compare with `services/recommendation_service.py:382`
  (`if self._lastfm_enabled():`) which guards the Last.fm jobs in `_collect_uncached_candidates`.
- **Suggested fix:** Guard the Last.fm sections with `_lastfm_enabled()` and give the task an overall deadline
  (or move the section builders into the bounded executor used by `_collect_uncached_candidates`).
- **Fix side effects:** With no key the home feed would lose its "Топ-чарты"/"Новые релизы" sections — but those are
  already empty in that case, so the visible change is nil.
- **Discovered by:** A

---

### 3. Clean areas

- **Scoring is bounded and NaN-safe.** `RecommendationService._calculate_taste_weights`
  (`services/recommendation_service.py:209-225`) computes `affinity*.35 + recent*.1 + favorite*.1 + relevance*.35 +
  genre_score*.1`, i.e. ≤ 1.0, plus a `+0.18` novelty bonus in `_rank_tracks` (L287) and a `-1` skip penalty (L289).
  `affinity` is `log1p(score)/log1p(maximum) if maximum else 0` — the division-by-zero case is explicitly guarded, and
  `maximum` is the max of the same dict, so `affinity ∈ [0,1]`. `genre_score` comes from a normalised
  `genre_distribution` (`services/taste_profile.py:295-299`, values sum to 1) and configured genres clamped to 1.
  `recommendation_relevance` is produced by the provider fan-out as `rank * weight` with `rank = 1/(1+position*.18)`
  and `weight ≤ .95` (`services/recommendation_service.py:411-416`), and is additionally clamped by `_bounded_score`
  (`min(1.0, max(0.0, score))`, NaN → 0). The score is never exposed to the UI (`recommendation_relevance` has no
  consumer in `ui/web_new_v2/js/**`), so an out-of-range value could not corrupt a percentage.
- **Empty / malformed input is handled.** `_rank_tracks` clamps `limit` to `[0,50]` and returns `[]` for 0
  (L236-238); `_format_ui_track` returns `{}` for a non-dict and coerces a NaN/inf/negative duration to `0.0`
  (L84-111, pinned by `tests/test_recommendation_service.py:200-204`); `_collect_uncached_candidates` skips
  non-dict items and candidates without a title (L402-410); `_feedback()` tolerates non-list settings values (L151-155).
  `UserTasteProfile` tolerates tracks without an artist (`_get_artist` returns `None` → the row is skipped, L545-550)
  and without a genre (`_add_genre` skips empty values, L277-280); `_field()` swallows `IndexError/KeyError/TypeError`
  for non-dict rows (L535-543).
- **Provider fan-out is time-bounded and failures are isolated.** `_collect_uncached_candidates` caps the provider wait
  at 8 s and the whole batch at a 12 s deadline (L367, L389), cancels the pending futures, and catches per-future
  exceptions individually (`self.logger.debug('Recommendation provider unavailable: %s', exc); continue`, L396-400) —
  one dead provider does not sink the batch. The metadata-resolution step is separately guarded (L447-448).
- **Deduplication works.** Candidates are deduplicated by content key (`by_content`, L392-432) and again in
  `_rank_tracks` by content key and by `(source, source_id)` (`seen` / `seen_ids`, L283-286), so the same track from
  two providers cannot appear twice.
- **`exclude_ids` is honoured.** `services/recommendation_service.py:272-283` matches the excluded ids against the
  track's `id`, `source_id`, the original ids, and the `artist:title` content key; `get_wave_for_track` additionally
  adds the seed's own `id`/`source_id` (L909-910). Pinned by
  `tests/test_recommendation_service.py:101-118`.
- **The feedback path persists and is applied.** `core/api.py:2979-3000` writes
  `personalization.blocked_artists` / `personalization.disliked_tracks` through `SettingsManager.set` (which is
  persisted to SQLite by the batched writer) and caps the list at the newest 1000 entries. Verified end-to-end that a
  blocked artist and a disliked track are removed from the ranked result:
  ```
  no blocks ->        ['Alpha', 'Beta', 'Gamma']
  artist blocked ->   ['Alpha', 'Gamma']
  track disliked ->   ['Gamma']
  ```
- **The profile is invalidated correctly when new listening data arrives.** `PRAGMA data_version` changes when another
  connection commits, so a new `history` row (written by `begin_listening_session`, `core/database.py:1558-1567`)
  invalidates the cached profile even though the reading thread's own `total_changes` is unchanged. Verified: an
  external write flipped the profile from `['Artist']` to the empty-profile defaults.
- **"Now" is computed once per profile build** (`now = datetime.now()`, `services/taste_profile.py:225`), so a build at
  23:59:59 and one at 00:00:01 use a single consistent instant for all recency factors in that build.
- **Listening dedup is sound.** `DatabaseManager.record_listening_once` is a deprecated
  `raise NotImplementedError` (`core/database.py:1320-1338`) with no callers, so it can neither double-record nor drop
  a listen. The live path is `AppApi.maybe_log_history` → `begin_listening_session` (one INSERT per listening session,
  guarded by `if session.history_id is not None: return`, `core/api.py:1312-1313`) and `_persist_listening` →
  `update_history_duration` (an UPDATE, so re-persisting is idempotent, `core/api.py:1290-1295`).
  (`AppApi._history_logged_key` is written but never read — vestigial; that is WN-05 territory, not reported here.)
- **The profile cache is properly guarded.** The module-level `_profile_cache` is only touched under
  `_profile_cache_lock` (`services/taste_profile.py:26-27, 376, 391`), no nesting → no deadlock; cached state is
  deep-copied in and out, so a caller mutating a returned track cannot poison the cache (pinned by
  `tests/test_taste_profile.py:123-132`).
- **`RecommendationService`'s shared state joins the class lock** (rule 2 of `AGENTS.md`): `_candidate_flights` and the
  `_search_cache` are guarded by `BaseMusicService._cache_lock`, no second lock is opened.

---

### 4. Coverage gaps

- **No live providers were exercised.** YouTube / SoundCloud / Last.fm / iTunes were never contacted (no network, and
  the audit rules forbid running the real app), so all statements about provider latency, rate limiting and real
  payloads are derived from the code and from stubbed probes, not from production traffic.
- **`get_recommendations_quality` was read but not exercised.** `core/database.py:1569-1584` groups by
  `recommendation_context` (written by `begin_listening_session` from `track['recommendation_origin']`,
  `core/api.py:1325`); the context string is validated against `('feed','mix','wave','flow','artist')`
  (`core/database.py:1560`). I did not verify that every origin actually emitted by the service
  (`'feed'`, `'mix'`, `'wave'`, `'flow'`, `'artist'`) reaches that whitelist — `recommendation_origin` is set in
  `_feed_tracks`, `get_releases`, `get_mixes`, `get_wave_for_track` and `get_flow_tracks_sync`
  (`services/recommendation_service.py:476, 687, 702, 910, 917`) and all five are in the whitelist, but the end-to-end
  aggregation was not run against a populated history.
- **UI-side rendering was not reviewed.** The shape parity between `_format_ui_track`
  (`services/recommendation_service.py:84-111`) and the raw provider dicts returned by `AppApi.search`
  (`core/api.py:2077+`) is a WN-28/WN-31 question; I only confirmed that both are consumed by the same track renderer
  and that no UI code reads `recommendation_relevance` / `recommendation_source`.
- **Concurrency was probed with threads, not with the real pywebview dispatch.** The thread-local-connection finding
  (F-WN-23-3) was reproduced with plain threads, which is exactly how `DatabaseManager` behaves, but I did not measure
  the request rate of the real UI.
- **`core/services/recommendation.py` was not executed against a realistic catalog.** The `KeyError` was reproduced
  with a minimal catalog; the "always-empty sections" claim was derived from the schema in `core/database.py:213-239`
  rather than from a populated `tracks` table.
