## AREA WX-08 — Recommendation loop: taste profile → recommendations → feedback → taste profile — ROLE A

### 1. Scope reviewed

**Files opened (path: line ranges actually read)**

| Path | Lines read |
|---|---|
| `docs/audits/WIN_AUDIT_CONTEXT.md` | 1–200 (whole) |
| `docs/audits/WIN_AUDIT_AREAS.md` | 1–70 (whole) |
| `services/taste_profile.py` | 1–634 (whole) |
| `services/recommendation_service.py` | 1–917 (whole) |
| `core/services/recommendation.py` | 1–240 (whole) |
| `core/api.py` | 470–529, 1180–1546, 2615–2659, 2940–3079, 3260–3609, 3700–3819, 4105–4134 |
| `core/database.py` | 140–319, 1054–1128, 1240–1399, 1540–1669, 1695–1744 |
| `core/app.py` | 205–264 |
| `core/settings.py` | 160–184, 345–434 |
| `services/base_service.py` | 1–329 (whole) |
| `services/artist_identity.py` | 1–63 (whole) |
| `services/track_resolver.py` | 140–179, 330–449 |
| `services/youtube_service.py` | 196–250, 510–645 |
| `services/lastfm_service.py` | 40–119, 320–340 |
| `ui/web_new_v2/js/home.js` | 1–1049 (whole) |
| `ui/web_new_v2/js/utils.js` | 1050–1328 |
| `ui/web_new_v2/js/events.js` | 130–234 |
| `ui/web_new_v2/js/player.js` | 1515–1584 |
| `audio/engine.py` | 1–110 |
| `tests/test_recommendation_service.py` | 1–204 (whole) |

**Callees traced into other areas**

- `core/database.py::get_history` (WN-12) — row shape consumed by the profile.
- `core/database.py::begin_listening_session` / `update_history_duration` (WN-12) — the history write path.
- `core/database.py::add_track` / `ensure_track_exists` (WN-12) — track identity for a recommendation played for the first time.
- `core/settings.py::get/set` (WN-14) — where `blocked_artists` / `disliked_tracks` live.
- `services/artist_identity.py` (WN-18) — `canonical_artist` / `track_key` used for every block/dedup comparison.
- `services/track_resolver.py` (WN-18) — `resolve_tracks` used to turn provider metadata into playable tracks.
- `services/youtube_service.py`, `services/lastfm_service.py`, `services/soundcloud_service.py` (WN-19/21) — the fan-out providers.
- `audio/engine.py` (WN-17) — carries `recommendation_origin` into `_current_track`.

**Scenario trace (as implemented)**

```
history rows (SQLite)
  → UserTasteProfile.build_from_db            services/taste_profile.py:60
  → RecommendationService._profile(history)    services/recommendation_service.py:173   ← MERGE (F-1)
  → _feed_tracks / _rank_tracks                services/recommendation_service.py:451 / :235  ← live scoring core
  → AppApi.get_feed → "feed_ready"             core/api.py:3740
  → js/home.js:182 requestHomeSection('home-recommended','get_feed',[10])
  → js/events.js:171 'feed_ready' → renderRecommendations
  → user plays  → js/home.js:776 play_track
  → AppApi.maybe_log_history / begin_listening_session  core/api.py:1304 / core/database.py:1558
  → user blocks → AppApi.set_recommendation_feedback     core/api.py:2979 → settings 'personalization'
  → back into _feedback() / _rank_tracks
```

`core/services/recommendation.py` is **not** in this trace — see **F-WX-08-3**.

---

### 2. Findings

#### F-WX-08-1  [P1] — The profile/history merge strips the measurement columns, so the "skipped track" demotion never fires for the 30 most recently played tracks

- **File:** `services/recommendation_service.py:173-185` (`_profile`), `services/recommendation_service.py:255-266` + `:287-289` (skip detection / demotion), `core/database.py:1599-1624` (`get_history`, the row source)
- **Confirmed:** yes
- **Description:** `RecommendationService._profile(history)` overwrites `profile.recent_history` with a merge of the caller-supplied `history` (which is `db.get_history(limit=30)`) and the profile's own history rows. The merge keeps the **first** occurrence of each content key, and the caller's rows come first. `db.get_history()` does not select `t.duration`, `h.completed`, `h.listening_measured`, `h.media_listened` or `h.session_finished`, so the merged rows carry `duration = None`. The skip detector in `_rank_tracks` requires `duration` to be truthy, so it never classifies those rows as skipped, and the `score -= 1` demotion is never applied to them.
- **Cause:** two different row shapes for "recent history" are merged with first-wins semantics, and the lossy shape wins. The measurement columns exist in the DB (`history.listening_measured`, `history.media_listened`, `history.session_finished`, `tracks.duration`) and are written correctly by `begin_listening_session` / `update_history_duration`, but the bridge-side query drops them before the profile sees them.
- **Trigger conditions:** any user with ≥1 play. `core/api.py:3742` always passes `history = db.get_history(limit=30)` into `RecommendationService.get_feed`, so the merge always runs on the home feed path (`get_authentic_home_feed` at `core/api.py:3337` uses `get_user_history_tracks`, which selects `t.*` — it has `duration` but still no `completed` / `listening_measured` / `media_listened` / `session_finished`, so it fails the same test).
- **User impact:** the app measures skips carefully (a dedicated `history.listening_measured` / `media_listened` / `session_finished` triple, a `skips` counter in `DatabaseManager.get_recommendation_quality`, `core/database.py:1569`), but the recommender never uses that measurement for the tracks the user actually skipped most recently — so the "I skipped this and it came back" complaint is real, and `get_recommendation_quality` reports skips that the ranker ignored.
- **Evidence:**
  ```python
  # services/recommendation_service.py:173
  def _profile(self, history=None):
      profile = UserTasteProfile(settings=self.settings).build_from_db(self.db) if self.db else UserTasteProfile(settings=self.settings)
      if history:
          merged, seen = [], set()
          for track in list(history) + profile.recent_history:   # caller's lossy rows come FIRST
              ...
              if key not in seen:
                  seen.add(key)
                  merged.append(track)
          profile.recent_history = merged[:50]                  # lossy rows win
  ```
  ```python
  # core/database.py:1608  (get_history — no duration / completed / listening_measured / media_listened / session_finished)
  SELECT t.id AS track_id, MAX(h.played_at) AS played_at, COUNT(*) AS play_count,
         COALESCE(SUM(h.duration_listened), 0) AS duration_listened,
         t.title, t.artist, t.album, t.cover_path, t.cover_url, t.source, t.source_id
  FROM history h JOIN tracks t ON h.track_id = t.id GROUP BY t.id ORDER BY played_at DESC LIMIT ?
  ```
  ```python
  # services/recommendation_service.py:256
  for track in profile.recent_history:
      listened, duration = track.get('duration_listened'), track.get('duration')
      if track.get('listening_measured') and not track.get('session_finished'):
          continue
      if listened is not None and duration and not track.get('completed') and not track.get('is_favorite'):
          #      ^^^^^^^^^^^^^^^ None for every merged row -> branch never taken
  ```
  ```python
  # services/recommendation_service.py:287
  score = self._calculate_taste_weights(track, profile) + (0.18 if key not in known else 0)
  if key in skipped:
      score -= 1
  ```
- **Reproduction / verification:** scratch probe `%TEMP%\opencode\wx08_probe.py` (a temp SQLite DB with one track and one measured 2-second skip):
  ```
  A) build_from_db recent_history[0]: duration=180.0 duration_listened=2.0 completed=0
                                   listening_measured=1 media_listened=2.0 session_finished=1
  B) db.get_history(limit=30) row:   duration=None completed=None listening_measured=None
                                   media_listened=None session_finished=None
  C) after _profile(history) merge:  duration=None completed=None listening_measured=None
                                   media_listened=None session_finished=None
  D) skipped set after merge      : set()
     skipped set WITHOUT the merge : {('artist', 'skipped song')}
  ```
  The existing unit test `tests/test_recommendation_service.py:93` (`test_measured_skip_does_not_outrank_another_candidate`) passes only because its fixture injects `duration=180` into the fake row — a shape the production merge never produces.
- **Suggested fix:** keep the measurement-bearing rows. Either (a) let `get_history` also select `t.duration`, `MAX(h.completed)`, `MAX(h.listening_measured)`, `MAX(h.media_listened)`, `MAX(h.session_finished)`; or (b) merge with the profile's own rows winning (they are the ones that carry the measurement columns); or (c) make `_rank_tracks` fall back to `tracks.duration` looked up by `track_id` when `duration` is absent. Option (a) alone is not sufficient for `get_user_history_tracks` (see `core/database.py:1238`), so (b) is the safer fix.
- **Fix side effects:** (a) widens the `get_history` projection — every caller of `get_history` (home dashboard, `get_home_data`, `get_authentic_home_feed`, `get_profile_stats`) gets four extra columns; harmless but changes the row shape that `home.js` receives. (b) changes which row wins for duplicated content keys and could reorder `recent_history` relative to `played_at` (the two sources are both `played_at DESC`, so ordering stays compatible). (c) adds a per-candidate DB lookup — avoid.
- **Discovered by:** A

#### F-WX-08-2  [P2] — `AppApi.get_recommendations` gives up after 3 s while the wave fan-out is budgeted for 12 s; the late result is discarded

- **File:** `core/api.py:3537-3553` (`get_recommendations`), `services/recommendation_service.py:366-390` (`_collect_uncached_candidates`)
- **Confirmed:** yes
- **Description:** the bridge method waits 3.0 s on a `threading.Event` and then returns whatever has arrived. The work it waits for is `RecommendationService.get_recommendations` → `get_wave_for_track` → `_collect_candidates` → `_collect_uncached_candidates`, whose own budget is a 12 s deadline with an 8 s provider wait. When the providers are cold or slow the event is set after the bridge has already returned, and the callback's `res.extend(tracks)` writes into a list nobody reads any more.
- **Cause:** the caller's timeout budget (3 s) is far below the callee's timeout budget (12 s), and the bridge method is synchronous-by-`Event` rather than event-based.
- **Trigger conditions:** cold provider cache, slow/absent network, a provider that needs >3 s to answer. `RecommendationService.get_recommendations` submits the task to the shared 8-worker pool (`services/base_service.py:124`), so under load the queueing delay alone can exceed 3 s.
- **User impact:** the endpoint returns `[]` — the caller sees "no recommendations" rather than "slow". The late tracks are computed, paid for, and thrown away. Currently no shipped UI calls `api.get_recommendations` (grep over `ui/` finds none), so the blast radius today is limited to direct/API callers and to the offline-interception branch at `core/api.py:492`; the code path is nonetheless the documented entry point named by this scenario.
- **Evidence:**
  ```python
  # core/api.py:3537
  def get_recommendations(self, track_data: dict, max_results: int = 10):
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
          evt.wait(timeout=3.0)          # <-- 3 s
      except Exception as e:
          logger.error(f"Error in get_recommendations: {e}")
      return res[:max_results]            # <-- late callback result lost
  ```
  ```python
  # services/recommendation_service.py:366
  def _collect_uncached_candidates(self, seeds, artists, limit):
      deadline = time.monotonic() + 12.0        # 12 s budget
      ...
      done, pending = wait(futures, timeout=min(8.0, max(0, deadline - time.monotonic()))) if futures else (set(), set())
  ```
- **Reproduction / verification:** stub `youtube_service.get_related_tracks_sync` to sleep 6 s and return one track; call `AppApi.get_recommendations(seed, 5)`; assert the returned list is `[]` while the stub was invoked. Equivalently: `RecommendationService.get_recommendations` completes at ~6–12 s, `evt.wait(3.0)` returns `False` at 3 s.
- **Suggested fix:** make the method event-based like the sibling `get_track_wave` (`core/api.py:3555`, which returns `[]` immediately and publishes `track_wave_ready`), or raise the wait to at least the service's 12 s budget and keep the result if it arrives before the method returns.
- **Fix side effects:** event-based delivery changes the bridge contract (callers must listen for an event) and would break `tests/test_recommendation_bridge.py:15-17`, which asserts the method returns a list synchronously. Raising the timeout blocks the calling thread for up to 12 s — pywebview runs API calls off the UI thread, but the caller still sees a 12 s promise.
- **Discovered by:** A

#### F-WX-08-3  [P2] — `core/services/recommendation.py` is not part of the recommendation loop at all (dead module); the live scoring core is `RecommendationService._rank_tracks`

- **File:** `core/services/recommendation.py:1-240` (whole module), `services/recommendation_service.py:235-324` (`_rank_tracks`, the live scorer)
- **Confirmed:** yes
- **Description:** the scenario (and the area map, WN-23) names `core/services/recommendation.py` as "the scoring core". Nothing imports it. `RecommendationEngine`, `run_recommendation` and `build_real_engine` have zero call sites in production code; the only references are the module's own definitions. The scoring that actually produces the user's recommendations is `RecommendationService._rank_tracks` + `_calculate_taste_weights`.
- **Cause:** the module was written against a different data model (`user_profile` dict with `history`/`favorites`/`skips`/`repeats` keys and a catalogue of tracks carrying `bpm`/`energy`/`mood`/`acoustics`/`bass`) and was never wired to `UserTasteProfile` or to the provider layer.
- **Trigger conditions:** always — the module is never executed.
- **User impact:** no direct runtime impact (it is dead code), but the risk is real for anyone acting on this audit map: a fix applied to `core/services/recommendation.py` would change nothing the user sees, and the audit of "the scoring core" would silently review the wrong file. The dead module is also *not* a safe template for the live one: it is non-deterministic and would raise on real data.
- **Evidence:**
  ```python
  # core/services/recommendation.py:56 — unseeded RNG, order is not reproducible
  familiar_count = int(count * random.uniform(0.6, 0.7))
  ...
  selected.extend(random.sample(familiar_pool, familiar_count))   # :66
  selected.extend(random.sample(discovery_pool, discovery_count))   # :72
  random.shuffle(selected)                                          # :76
  ```
  ```python
  # core/services/recommendation.py:134 — set.pop() on an unordered set: the "artist radio" is arbitrary
  radio_artist = self.subs_set.copy().pop() if self.subs_set else None
  ```
  ```python
  # core/services/recommendation.py:48 — KeyError on any catalogue row without 'id'
  return [t for t in self.catalog if self.skips.get(t["id"], 0) <= self.skip_penalty_threshold]
  ```
  Reachability check (repo-wide grep for `core.services.recommendation`, `run_recommendation`, `build_real_engine`, `RecommendationEngine`): the only hits are the definitions themselves in `core/services/recommendation.py` and `services/lastfm_service.py:157` (an unrelated `User-Agent` string).
- **Reproduction / verification:** `grep -rn --include=*.py -e "core.services.recommendation" -e "run_recommendation" -e "build_real_engine" <repo root>` → no importer outside the module itself. Confirmed by reading `core/app.py:213-234` (the `recommendations` property constructs `services.recommendation_service.RecommendationService`, not `core.services.recommendation`).
- **Suggested fix:** either delete `core/services/recommendation.py`, or — if it is meant to be the "engine" — port its ideas into `RecommendationService` and delete the duplicate. At minimum, correct the audit map / area description (WN-23) so the next reviewer reads `services/recommendation_service.py`.
- **Fix side effects:** deleting the module is safe for the app (nothing imports it) but any external script/test that imports it would break — repo-wide grep shows none. Re-pointing the audit map has no runtime effect.
- **Discovered by:** A

#### F-WX-08-4  [P3] — A "block everything" state empties the home feed with no fallback

- **File:** `services/recommendation_service.py:283` (blocked filter), `services/recommendation_service.py:474` (fallback gate), `services/recommendation_service.py:330-335` (`_collect_candidates` seed filtering)
- **Confirmed:** yes (code path); the "all artists blocked" precondition is user-driven, not a bug in itself
- **Description:** the curated-welcome fallback only fires when the profile is completely empty **and** has no recent history. A user who has a history and blocks every artist in it ends up with an empty feed and no fallback: every familiar track is filtered by `key[0] in blocked`, every seed is filtered by `_seed_tracks`, every seed artist is filtered by `_get_merged_seed_artists`, so `_collect_candidates` returns nothing and `_rank_tracks` returns nothing.
- **Cause:** the fallback condition is `profile.is_empty() and not profile.recent_history`, i.e. "no taste at all", not "no taste left after filtering".
- **Trigger conditions:** the user blocks each artist that appears in their history/favourites (the UI offers exactly this: `utils.js:1161` "Не рекомендовать артиста"). A single block is harmless — verified by probe: with `Artist A` blocked, `_rank_tracks` returned only `Hit B` and the feed still had content.
- **User impact:** the "Рекомендации" tile on the home page renders the empty state ("Нет данных") with no explanation and no way back other than un-blocking manually in settings; the curated onboarding tracks that a brand-new user would have seen are never offered.
- **Evidence:**
  ```python
  # services/recommendation_service.py:283
  if key[0] in blocked or key in seen or key in excluded_content or ids.intersection(excluded) or provider_id in seen_ids:
      continue
  ```
  ```python
  # services/recommendation_service.py:474
  if not tracks and profile.is_empty() and not profile.recent_history:
      tracks = self._rank_tracks(CURATED_WELCOME_TRACKS, profile, max_results)
  ```
  ```python
  # services/recommendation_service.py:333
  blocked, disliked = self._feedback()
  seeds = [t for t in seeds if self._artist_key(t) not in blocked and self._content_key(t) not in disliked]
  artists = [a for a in artists if self._artist_key(a) not in blocked]
  ```
- **Reproduction / verification:** scratch probe `%TEMP%\opencode\wx08_probe2.py` section H — with `blocked_artists = ["Artist A"]` the ranking drops `Hit A` and keeps `Hit B` (block applied correctly). Extending the block list to every artist in `profile.top_artists` yields `[]` from `_rank_tracks`, and the fallback at line 474 is skipped because `profile.is_empty()` is False.
- **Suggested fix:** broaden the fallback to "the filtered result is empty", e.g. `if not tracks and (profile.is_empty() or not profile.recent_history):` plus a curated set that excludes blocked artists, or emit a dedicated "you blocked everything" state.
- **Fix side effects:** a broader fallback would also fire for transient provider outages (all candidates empty) and would replace a legitimately empty result with generic content — the current behaviour of showing "Нет данных" during an outage is arguably better. The fix must keep the blocked-artist filter applied to the curated list.
- **Discovered by:** A

#### F-WX-08-5  [P3] — The dedup key named by the scenario does not exist: `record_listening_once` is removed and `_listening_identity` is not a dedup key; `AppApi._history_logged_key` is write-only dead state

- **File:** `core/database.py:1320-1338` (`record_listening_once`), `core/api.py:1262-1265` (`_listening_identity`), `core/api.py:1212`, `:1328`, `:1372` (`_history_logged_key`)
- **Confirmed:** yes
- **Description:** the scenario describes `record_listening_once(track_id, dedup_key)` as the dedup mechanism with the key built by `_listening_identity`. In the current code `record_listening_once` was deliberately deleted and now raises `NotImplementedError`; `_listening_identity` is used only to decide whether two dicts describe the same track (session reuse in `_listening_for_track`, and index matching in the offline branch of `play_track`); and `AppApi._history_logged_key` is assigned in three places and never read. The *effective* dedup is `maybe_log_history`'s `if session.history_id is not None: return` — one `history` row per listening session, keyed by the session token.
- **Cause:** the dedup was moved from a persistent DB-side key to a process-local listening-session token; the dead field and the stale docstring were left behind.
- **Trigger conditions:** always (the dead field and the removed method are unconditional).
- **User impact:** none directly — the loop does not double-count a single playback and does not drop a distinct one (verified below). The impact is on the audit contract: a reviewer following the scenario text would look for a dedup window that does not exist, and `core/database.py`'s own docstring still advertises the removed mechanism.
- **Evidence:**
  ```python
  # core/database.py:1320
  def record_listening_once(self, track_id: int, dedup_key: str) -> bool:
      """DEPRECATED and unused - do not reintroduce.
      ...
      Playback deduplication belongs to the caller and stays process-local:
      AppApi.maybe_log_history() keeps _history_logged_key under
      _window_op_lock and resets it when the track changes or playback stops.
      """
      raise NotImplementedError(...)
  ```
  ```python
  # core/api.py:1262
  @staticmethod
  def _listening_identity(track):
      return (str(track.get('source') or ''), str(track.get('source_id') or track.get('id') or ''),
              str(track.get('artist') or ''), str(track.get('title') or ''))
  ```
  ```python
  # core/api.py:1328 — written, never read
  self._history_logged_key = track.get('source_id') or t_id
  ```
  Repo-wide grep for `_history_logged_key`: 3 writes (`core/api.py:1212`, `:1328`, `:1372`) and 0 reads outside `core/database.py`'s docstring and two tests.
- **Reproduction / verification:** `grep -rn "_history_logged_key" <repo root>` → only the assignments above plus `tests/test_api_f1_audit.py:355` and `tests/test_db_core_fixes_f2.py:230`, which assert the *absence* of the old DB-side dedup. `record_listening_once` raises `NotImplementedError` (pinned by `tests/test_api_f1_audit.py:372-380`). The live dedup: `core/api.py:1312` `if session.history_id is not None: return` — one `history` row per session; a track change creates a new session (`core/api.py:1277-1283`), a pause/resume reuses the open session, and `report_state('stopped')` closes it (`core/api.py:1368-1369`), so a replay produces a second, distinct row. The session list is capped at 32 (`core/api.py:1284`), so the dedup window is bounded by 32 sessions, not by time.
- **Suggested fix:** delete `AppApi._history_logged_key` and update the `record_listening_once` docstring to describe the session-token mechanism; drop the `record_listening_once` stub (or keep it as a guard, but stop documenting it as the active contract). Also record the actual dedup semantics in the area map.
- **Fix side effects:** the two tests that mention `_history_logged_key` only assert the DB-side dedup is *not* used (`test_api_f1_audit.py:355` "the dedup must live in `_history_logged_key`, not in the database"), so removing the field will require updating that test's wording. No runtime effect otherwise.
- **Discovered by:** A

#### F-WX-08-6  [P3] — The recommendation feed and candidate caches live in the class-level search cache shared with every other service, and the feed is not cached at all when it is library-only

- **File:** `services/recommendation_service.py:466-479` (`_feed_tracks` cache), `services/recommendation_service.py:337-355` (`_collect_candidates` cache), `services/base_service.py:132-134` + `:244-276` (shared cache)
- **Confirmed:** yes
- **Description:** two issues in the same cache layer. (a) `RecommendationService` inherits `BaseMusicService._search_cache`, a **class-level** dict with a 300-entry LRU shared with YouTube/SoundCloud/Last.fm/Lyrics search results. Recommendation entries are therefore evicted by unrelated services' traffic. (b) The feed result is written only `if tracks and candidates` — a feed built purely from the local library (no provider candidates) is recomputed on every call; and the candidate set is cached only when non-empty (`if candidates:`), so an empty candidate set re-runs the whole 8-second provider fan-out on every request.
- **Cause:** the cache was bolted onto the shared base-class cache instead of a service-local one, and the write conditions were written for the happy path only.
- **Trigger conditions:** (a) any app with heavy search usage; (b) any request where the providers return nothing (offline, provider outage, all candidates filtered as unplayable) — the fan-out is repeated at full cost per request.
- **User impact:** with an empty candidate set the home feed pays the full fan-out budget (up to 8 s of provider wait, `services/recommendation_service.py:389`) on every "Рекомендации" refresh, and the request is only bounded by the 12 s deadline, so the home page can hang on a skeleton for seconds with nothing to show. Cache eviction under search pressure makes the feed recompute more often than the 5-minute TTL implies.
- **Evidence:**
  ```python
  # services/base_service.py:132
  _search_cache: Dict[str, Dict[str, Any]] = {}
  _SEARCH_CACHE_TTL = 300
  _SEARCH_CACHE_MAX_SIZE = 300
  ```
  ```python
  # services/recommendation_service.py:477
  if tracks and candidates:
      self.set_search_cache(key, [dict(t) for t in tracks])
  ```
  ```python
  # services/recommendation_service.py:353
  candidates = self._collect_uncached_candidates(seeds, artists, limit)
  if candidates:
      self.set_search_cache(key, [dict(t) for t in candidates])
  ```
  (`RecommendationService.reset_service()` at `services/recommendation_service.py:64-68` can only drop `recommendation:`-prefixed keys from the shared cache — it cannot prevent other services from evicting them.)
- **Reproduction / verification:** fill `BaseMusicService._search_cache` with 300 non-recommendation entries and call `RecommendationService.get_feed` twice with an unchanged profile; the second call re-runs the fan-out instead of hitting the cache. Separately, with `youtube_service.get_related_tracks_sync` returning `[]`, two consecutive `get_feed` calls each spend the full fan-out window.
- **Suggested fix:** give `RecommendationService` its own cache dict (still guarded by the inherited `_cache_lock`), cache the empty candidate result with a short TTL, and cache the library-only feed as well (the `tracks and candidates` condition should be `if tracks:`).
- **Fix side effects:** a service-local cache duplicates a little bookkeeping but removes cross-service eviction; caching empty results delays recovery after a provider outage by the chosen TTL (keep it short, e.g. 30–60 s); caching the library-only feed means the feed stops reflecting library changes until the TTL expires — the feed key already includes the library identity fields (`is_favorite`, `is_downloaded`, `file_path`), so this is acceptable.
- **Discovered by:** A

#### F-WX-08-7  [P3] — Two different notions of "top artists" drive the home tile and the recommendations

- **File:** `core/database.py:1708-1721` (`get_top_artists`), `services/taste_profile.py:224-273` (`top_artists`), `core/api.py:3300-3312` (`get_home_data`)
- **Confirmed:** yes
- **Description:** the home page's "Топ-исполнители" tile comes from `db.get_top_artists()`, which groups the `tracks` table by the **raw** artist string and orders by `SUM(play_count)` (raw playback count, no recency). The recommendation profile's `top_artists` canonicalises the artist name (`canonical_artist`: NFKC + case-fold + alias table), weights each signal (like 3, download 3, completed play 2, play 1) and multiplies by a 30-day recency half-life. The two lists therefore routinely disagree in membership and order.
- **Cause:** two independent "top artist" definitions were implemented in two layers and never reconciled; the profile needed canonicalisation + recency for ranking, the dashboard wanted a cheap aggregate.
- **Trigger conditions:** always, for any library with more than one spelling of an artist (e.g. "Eminem" / "EMINEM" / "Eminem feat. …"), or with listens spread over months.
- **User impact:** the user sees a "Топ-исполнители" list that does not explain the recommendations next to it — the artists driving the recommendation ranking are not the ones listed, and vice versa. It also makes the recommendation behaviour hard to reason about from the UI.
- **Evidence:**
  ```python
  # core/database.py:1708
  def get_top_artists(self, limit: int = 10) -> List[Dict[str, Any]]:
      cursor.execute(
          """
          SELECT artist, COUNT(*) as track_count, SUM(play_count) as total_plays, ...
          FROM tracks
          WHERE artist != 'Unknown Artist'
          GROUP BY artist
          ORDER BY total_plays DESC
          LIMIT ?
          """, (limit,))
  ```
  ```python
  # services/taste_profile.py:224 — canonicalised keys, weighted, recency-boosted
  self._artist_scores = defaultdict(float)
  ...
  for row in history_rows:
      ...
      _add_signal(row, self._listening_weight(row) * recency)
  ```
  ```python
  # core/api.py:3301 — the dashboard uses the raw aggregate
  top_artists = self._core.db.get_top_artists(limit=10) or []
  ```
- **Reproduction / verification:** store one track with artist `"eminem"` and one with `"EMINEM"` → `db.get_top_artists()` returns two rows; `UserTasteProfile.build_from_db()` returns a single merged artist (`canonical_artist` case-folds). `js/home.js:849 renderTopArtists` renders the former, `js/home.js:686 requestArtistAvatars` then asks the backend to resolve those raw names.
- **Suggested fix:** have `get_home_data` derive its "top artists" from the same taste profile (or expose `UserTasteProfile.top_artists`), or canonicalise inside `db.get_top_artists`. The dashboard tile is the cheaper place to change.
- **Fix side effects:** using the profile for the tile costs a profile build per home load (it is already built for the feed, and the profile cache makes it cheap). Canonicalising in SQL would break `artist != 'Unknown Artist'` filtering for non-ASCII names and change existing Wrapped/analytics exports.
- **Discovered by:** A

---

### 3. Clean areas

- **Profile cache invalidation is CORRECT.** `UserTasteProfile.build_from_db` memoises for 60 s (`services/taste_profile.py:24`) but invalidates on a content revision (`_connection_revision`, `services/taste_profile.py:357-371`) built from `conn.total_changes` + `PRAGMA data_version` + `schema_version`. Because `DatabaseManager` uses a **thread-local** connection (`core/database.py:151-205`), `total_changes` alone would miss writes made on another thread — but `PRAGMA data_version` covers exactly that case. Verified empirically (scratch probe `%TEMP%\opencode\wx08_probe.py` section E and `%TEMP%\opencode\wx08_probe3.py`):
  ```
  WAL cross-connection PRAGMA data_version: before=2 after cross-conn commit=3  changed=True
                                                total_changes before=0 after=0   changed=False
  cross-thread write  -> profile cache invalidated: True   (p1 ['Artist A'] -> p2 ['Artist B','Artist A'])
  same-connection write -> profile cache invalidated: True  (p3 -> p4 gained 'Artist C')
  ```
  A stale profile (the "same recommendations forever" failure mode) does **not** occur.
- **Profile input is a bounded, weighted, recency-decayed window.** `HISTORY_LIMIT = 1500` rows ordered by `played_at DESC` (`services/taste_profile.py:22`, `:143-151`); per-row weight = `WEIGHT_COMPLETED_PLAY 2 / WEIGHT_PLAY 1` scaled by a 30-day half-life (`_recency_factor`, `:580-586`); likes/downloads weight 3 (`WEIGHT_LIKE`, `WEIGHT_DOWNLOAD`); a measured 1–10 s audition is damped to 0.1 (`_listening_weight`, `:556-577`). `_recency_factor` uses `.timestamp()` on both sides, so aware/naive datetimes cannot raise.
- **Score normalisation is safe.** `_calculate_taste_weights` (`services/recommendation_service.py:209-225`) is a convex sum of five terms each bounded to [0,1] → total ≤ 1.0, plus a ≤0.18 discovery bonus; the skip demotion subtracts 1. `recommendation_relevance` is clamped by `_bounded_score` (`:227-233`) which also rejects NaN/inf (`math.isfinite`), and `duration` is coerced to a finite non-negative float (`:89-93`). Verified by probe: `recommendation_relevance` 5.0 → 1.0, `duration=NaN` → 0.0, `duration=-2` → 0.0 (also pinned by `tests/test_recommendation_service.py:200-204`). No UI code reads `recommendation_relevance` / `recommendation_origin` as a bar width (repo-wide grep over `ui/` finds no hits), so a >1 score cannot break a layout.
- **No division by zero and no empty-input crash.** `maximum = max(scores.values(), default=0)` with `if maximum else 0` (`:213-214`); `total_genre = sum(...) or 1` (`services/taste_profile.py:295`); `_rank_tracks` returns `[]` for an empty pool; `_feed_tracks` returns `[]` for `max_results <= 0`; `RecommendationService.get_feed` clamps `max_results` to [0,50] (`:627`) and `_rank_tracks` clamps again to [0,50] (`:236`).
- **The live ranking is deterministic.** `_rank_tracks` sorts by `(-score, index)` where `index` is the position in the input list (`services/recommendation_service.py:291`) — a total order with no ties, and no RNG anywhere in the live path. Verified: 5 identical `_rank_tracks` calls produced identical output. The candidate list order is deterministic too (`by_content` is an insertion-ordered dict filled in `futures` order, which follows the `jobs` list). The only `random` use in the whole recommendation area is in the **dead** module `core/services/recommendation.py` (see F-WX-08-3).
- **Duplicates within one list are prevented.** `_rank_tracks` keeps a `seen` set of content keys (`artist`, normalised title) and a `seen_ids` set of `(source, source_id)` (`:283-286`), and merges library identity into a candidate that matches a known track. Verified: two candidates with the same title/artist but different provider ids collapse to one entry.
- **The currently-playing track is excluded** from the feed: `_feed_tracks` passes `exclude_tracks=profile.recent_history[:1]` (`services/recommendation_service.py:472-473`), and the wave path excludes the seed by both content key and id (`get_wave_for_track`, `:909-910`).
- **Library tracks are not blindly re-recommended as strangers.** A candidate that matches a library track inherits the library row's `id`, `source`, `source_id`, `source_url`, `file_path`, `is_favorite`, `is_downloaded` (`:273-278`), so it plays the local file rather than a remote duplicate; familiar tracks are additionally capped at `max(1, round(limit*0.3))` entries and the per-artist cap is `max(2, ceil(limit/5))` (`:293-294`). This is pinned by `tests/test_recommendation_service.py:64-78` and `:121-130`.
- **The block IS persisted and IS applied.** `AppApi.set_recommendation_feedback` (`core/api.py:2979-3000`) writes `personalization.blocked_artists` / `personalization.disliked_tracks` through the shared `SettingsManager` (in-memory cache updated synchronously, `core/settings.py:401-418`), capped at 1000 entries. `RecommendationService._feedback()` (`:151-155`) reads them back on every ranking call, `_seed_tracks` / `_get_merged_seed_artists` drop blocked artists from the seed set, and `_rank_tracks` skips blocked artists (`:283`). Verified by probe: with `blocked_artists=["Artist A"]` the ranked output contained only `Artist B`. The feedback state is also part of the feed cache key (`repr(self._feedback())`, `:463`), so a block takes effect on the next feed request instead of waiting out the 5-minute TTL.
- **There is a positive "like" signal, and it is used.** `set_recommendation_feedback` is a block/unblock toggle only, but the positive signal is the favourites table: `AppApi.toggle_favorite` (`core/api.py:2615-2638`) → `db.toggle_favorite` sets `tracks.is_favorite` → `UserTasteProfile` reads `WHERE is_favorite = 1` with `WEIGHT_LIKE = 3.0` (`services/taste_profile.py:251-255`). The profile cache invalidates on that UPDATE (same connection → `total_changes`), and `is_favorite` is part of the feed cache key (`:456`).
- **The provider fan-out is bounded and provider failures are isolated.** At most 11 jobs are submitted (`services/recommendation_service.py:371-387`) to a 4-worker pool; the wait is capped at `min(8.0, deadline - now)` with a 12 s overall deadline (`:367`, `:389`); each provider has its own timeout (YouTube search `timeout=5` clamped to 6 s in `services/youtube_service.py:515-541`, the ytmusic `TimeoutSession` forces `timeout=6` at `:201-205`, Last.fm `timeout=5.0` at `services/lastfm_service.py:330`). A provider that raises is caught per-future and logged (`Recommendation provider unavailable`, `:398-400`) and the other providers' results are still used — pinned by `tests/test_recommendation_service.py:154-161`.
- **Results are normalised to one track shape and de-duplicated across providers.** `_format_ui_track` (`:84-111`) produces the same dict shape for every source (`id`, `title`, `artist`, `cover_url`, `source`, `source_id`, `source_url`, `file_path`, `duration`, `genre`, `recommendation_*`, `is_favorite`, `is_downloaded`), and the cross-provider merge key is the content key, with the playable variant winning and the strongest relevance kept (`:419-432`).
- **The consumer reads the fields the API returns.** `js/home.js:182` calls `get_feed` with `max_results = 10`; the backend honours it (`AppApi.get_feed` → `RecommendationService.get_feed` clamps to [0,50] → `_rank_tracks` clamps again → `AppApi.get_feed` slices `(tracks or [])[:max_results]`). `js/home.js:709 createFeedCard` reads only `type`, `cover_url`, `title`, `artist`, `source`, `source_id`, `duration`, `id` — all present in `_format_ui_track`. The `feed_ready` payload is a bare list and `js/events.js:171-177` accepts both a list and `{tracks}`.
- **The loop closes end to end.** `recommendation_origin` (`feed`/`mix`/`wave`/`flow`/`artist`) is set by the service, travels through `_format_ui_track` → the frontend card → `play_track` → `AudioEngine.play_queue` → `current.copy()` in `audio/engine.py:81` → `AppApi._on_track_changed` → `_current_track` → `AppApi.maybe_log_history` → `db.begin_listening_session` writes it to `history.recommendation_context` (`core/api.py:1325`, `core/database.py:1558-1567`). `core/database.py:1560` whitelists the origin values, so an arbitrary string cannot pollute the column.
- **The profile is rebuilt, not cached stale, when a like/block arrives.** The feed cache key embeds the profile's known-track signature (content keys, `is_favorite`, `is_downloaded`, `file_path`, `duration_listened`) and `repr(self._feedback())` (`:454-466`), so both a like and a block produce a new key and a fresh computation.

---

### 4. Coverage gaps

- **No live UI caller for `AppApi.get_recommendations`.** A repo-wide grep over `ui/` (including `index.html`) finds no `get_recommendations` call — only `get_flow_tracks` (`js/player.js:1553`), `get_feed` (`js/home.js:182`) and `get_home_data` (`js/home.js:99,118`). F-WX-08-2 is therefore a defect in a reachable-but-unused bridge method; I could not observe it end-to-end in the running app.
- **`js/library.js` is not part of the recommendation loop.** Grepping it for `recommend|feedback|dislike|wave` returns no matches; it neither consumes the feed nor sends feedback. The scenario names it as a consumer, but the feedback entry point is `js/utils.js::showTrackContextMenu` → `submitRecommendationFeedback` (`:1084`, `:1278-1283`), which is reachable from the library's context menu, not from `library.js` itself.
- **No provider was exercised against the network.** All fan-out behaviour was read from source and reasoned about, not measured. The 8 s/12 s budgets and the provider timeouts are taken from the code (`services/youtube_service.py:201-205`, `:515-541`, `services/lastfm_service.py:330`); the SoundCloud related-tracks timeout was not traced in detail (`services/soundcloud_service.py:960`).
- **`core/proxy.py` was not traced.** Whether a recommendation track with `id = None` (a candidate not yet in the library) resolves through the proxy was left to WX-01; `core/api.py:4110 get_flow_tracks` returns such rows and `maybe_log_history` calls `ensure_track_exists` for them (`core/api.py:1318`).
- **The `lastfm` path was not exercised.** `_lastfm_enabled()` (`services/recommendation_service.py:326-328`) requires an API key; with no key the Last.fm jobs are skipped entirely, so the "one provider's failure is isolated" claim was verified against the YouTube branch only (`tests/test_recommendation_service.py:154-161`).
- **Listening telemetry beyond the dedup was not audited.** The `report_state` / `report_listening_state` / `report_position` protocol (`js/player.js:532-1672`) and `core/listening.py` belong to WX-04 / WN-05; I verified only that the dedup outcome (one row per session) is what F-WX-08-5 describes.
- **The 32-session cap on listening sessions** (`core/api.py:1284`, `sessions.pop(next(iter(sessions)))`) can evict an *open* session whose history row keeps `session_finished = 0`; the effect on the profile's `_listening_weight` was not quantified (it maps an unfinished measured session to `WEIGHT_PLAY`, i.e. a full weight). Flagged to WN-05 / WX-04 rather than claimed here.
