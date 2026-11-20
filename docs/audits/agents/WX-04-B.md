## AREA WX-04 — Listening telemetry (player.js → AppApi → core/listening.py → core/database.py → services/listening_comparison.py → js/profile.js) — ROLE B

### 1. Scope reviewed

**Files opened (path: line ranges actually read)**

| Path | Lines read |
|---|---|
| `core/api.py` | 1–420 (ctor, `_emit`, bridge error wrapper), 595–614 (`_on_minimized`), 720–748 (`_deferred_window_op`), 900–959 (`close`/`shutdown`), 1115–1180 (`_emit`), 1180–1519 (`_on_track_changed`, `_listening_*`, `_persist_listening`, `flush_listening`, `maybe_log_history`, `report_listening_state`, `report_state`, `report_position`, `play_track`), 2230–2274, 2980–3019, 3095–3204 (`clear_storage`), 3280–3409 (`get_home_data`, `get_profile_stats`), 3460–3499, 4090–4139, 4210–4228 (`get_listening_comparison`) |
| `core/listening.py` | 1–44 (whole file) |
| `core/database.py` | 1–200 (conn/PRAGMA), 200–359 (schema + indexes), 1236–1319 (`get_user_history_tracks`, `log_listening_history`), 1478–1502 (`delete_track`), 1550–1669 (`begin_listening_session`, `update_history_duration`, `get_history`), 1715–1904 (`get_wrapped_stats`, `get_analytics_summary`), 2265–2304 (`add_listening_time`, `get_total_listening_time`) |
| `core/app.py` | 500–579 (`cleanup`) |
| `core/session.py` | 1–96 (whole file) |
| `core/settings.py` | 285–404, 415–494 (write-behind batching pattern) |
| `main.py` | 385–584 (`on_loaded`, `on_closed`, watchdog, post-loop cleanup) |
| `services/listening_comparison.py` | 1–84 (whole file) |
| `services/taste_profile.py` | 1–80 (`HISTORY_LIMIT`, `PROFILE_CACHE_TTL`) |
| `ui/web_new_v2/js/player.js` | 520–639 (audio events), 820–879 (seek), 1355–1384 (`isPlayerUiHidden`), 1630–1699 (`onTrackChanged`), 1920–1979 (`onPositionChanged`), 2110–2149 (`api()` helper) |
| `ui/web_new_v2/js/events.js` | 95–154 (`position_changed` handler) |
| `ui/web_new_v2/js/lyrics.js` | 295–334 (position sync) |
| `ui/web_new_v2/js/profile.js` | 100–179 (`loadProfile`, stat tiles) |
| `ui/web_new_v2/js/profile-comparison.js` | 1–56 (whole file) |
| `ui/web_new_v2/js/settings.js` | 200–279 (storage / clear-cache button) |
| `ui/web_new_v2/index.html` | 648 (comparison period `<select>`) |
| `utils/cache_manager.py` | 100–169 (`clear_all` and friends) |
| `.venv_win/Lib/site-packages/webview/util.py` | 295–354 (js_api dispatch) |
| `.venv_win/Lib/site-packages/webview/platforms/edgechromium.py` | 105–134 (`evaluate_js`) |
| `tests/test_measured_listening.py`, `tests/test_listening_comparison.py`, `tests/conftest.py` | whole files |

**Callees traced into other areas (owners named, not reviewed in depth)**

- **WN-12** `core/database.py` — history table, `get_wrapped_stats`, `get_analytics_summary`, `get_total_listening_time` → owner of F-WX-04-2, F-WX-04-4, F-WX-04-9.
- **WN-25** `services/listening_comparison.py` → owner of F-WX-04-1.
- **WN-32** `js/profile.js`, `js/profile-comparison.js`, `js/settings.js` — consumers of the telemetry data.
- **WN-23** `services/taste_profile.py` — checked for third-party egress of history (none; local read only).
- **WN-26** `core/services/discord_rpc.py` — checked for egress (sends the *current* track only, opt-in; out of WX-04 scope).

**Measurements performed** (scratch scripts under `%TEMP%\opencode\`, nothing in the repo tree, `~/.nedotify/` untouched): `wx04_chain.py` (one simulated hour of playback through the real `AppApi`), `wx04_bench.py` / `wx04_bench2.py` / `wx04_bench3.py` (write and scan costs), `wx04_final.py` (aggregation divergence), `wx04_plan.py` (`EXPLAIN QUERY PLAN`).

**Correction to the scenario brief.** The brief assumes `report_position` fires ~4×/s. It does not: the renderer throttles it to **one call every 5 s** (`ui/web_new_v2/js/player.js:611-616`). The HTML5 `timeupdate` event itself fires ~4×/s, but the bridge call is gated. The real rate is **0.2 calls/s = 720 calls per hour of playback**, and every one of them costs a SQLite write plus a blocking UI-thread round trip (quantified in §2).

---

### 2. Findings

#### F-WX-04-1  [P1] — `listening_comparison` is quadratic in the size of the history table: the "365 days" comparison takes 83 s at 50 000 rows

- **File:** `services/listening_comparison.py:56-81` (also `services/listening_comparison.py:29-45`)
- **Confirmed:** yes
- **Description:** The `new_artists` and `returning_artists` queries contain **correlated scalar subqueries whose inner `history` scan has no lower bound on `played_at`**. The inner index range `SEARCH old USING INDEX idx_history_played_at (played_at<?)` walks *every* history row older than the bound, and it is re-evaluated **once per outer row of the window** (the `GROUP BY` happens after the `WHERE`, so the subquery is not evaluated per artist group but per play). Cost ≈ (rows in window) × (rows in the whole history). The outer window is index-bounded, so the query looks index-backed in `EXPLAIN` — which is exactly why the defect is invisible in the plan but catastrophic in practice.
- **Cause:** The "artist existed before / did not exist before" predicate is expressed as an `EXISTS`/`NOT EXISTS` over the raw `history` table instead of over a pre-computed set of previously-seen artists (a CTE / temp table / `GROUP BY` subquery materialised once).
- **Trigger conditions:** Any history table with more than a few thousand rows. The user opens the profile page → "Сравнить периоды прослушивания" panel (`ui/web_new_v2/index.html:648` offers week / month / year) → `js/profile-comparison.js:33` → `AppApi.get_listening_comparison` (`core/api.py:4223-4225`).
- **User impact:** The comparison panel spins for seconds to minutes and then shows "Не удалось сравнить периоды" (`js/profile-comparison.js:38`) on any period whose window is non-trivial. Measured, on a 3-year spread of history at 30 plays/day with 400 distinct artists:

  | history rows | `week` | `month` | `year` |
  |---|---|---|---|
  | 5 000 | 9 ms | 42 ms | **789 ms** |
  | 15 000 | 83 ms | 267 ms | **8 689 ms** |
  | 30 000 | 606 ms | 2 521 ms | **32 993 ms** |
  | 50 000 | 2 030 ms | 6 692 ms | **82 895 ms** |

  Growth is ~O(N²) — 10× the rows ≈ 100× the time.
- **Evidence:**
  ```python
  # services/listening_comparison.py:56-66
  new_artists = [dict(row) for row in db.conn.execute('''
      SELECT t.artist, SUM(h.duration_listened) AS seconds
      FROM history h JOIN tracks t ON t.id = h.track_id
      WHERE h.played_at >= ? AND h.played_at < ? AND h.duration_listened > 0
        AND TRIM(COALESCE(t.artist, '')) != '' AND LOWER(t.artist) != 'unknown artist'
        AND NOT EXISTS (
            SELECT 1 FROM history old JOIN tracks older ON older.id = old.track_id
            WHERE old.played_at < ? AND old.duration_listened > 0
              AND LOWER(TRIM(older.artist)) = LOWER(TRIM(t.artist)))
      GROUP BY LOWER(TRIM(t.artist)) ORDER BY seconds DESC, t.artist LIMIT 10
  ''', (_stamp(current_start), _stamp(moment), _stamp(current_start)))]
  ```
  Query plan (`EXPLAIN QUERY PLAN`, measured):
  ```
  SEARCH h USING INDEX idx_history_played_at (played_at>? AND played_at<?)
  SEARCH t USING INTEGER PRIMARY KEY (rowid=?)
  CORRELATED SCALAR SUBQUERY 1
    SEARCH old USING INDEX idx_history_played_at (played_at<?)      <-- unbounded below
  USE TEMP B-TREE FOR GROUP BY
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wx04_bench3.py` (read-only against a throwaway DB in `%TEMP%`): seeds N history rows over the 3 years before a fixed `now`, then times `listening_comparison(db, period, 180)` for `week`/`month`/`year`. The table above is that script's output. No network, no `~/.nedotify/`, no repo files touched. The repo's own test (`tests/test_listening_comparison.py`) seeds **1–4 rows**, which is why the blowup was never caught.
- **Suggested fix:** Materialise the set of artists with history before `current_start` once (e.g. `WITH prev AS (SELECT DISTINCT LOWER(TRIM(t.artist)) a FROM history h JOIN tracks t ON t.id=h.track_id WHERE h.played_at < ? AND h.duration_listened > 0)`) and join/anti-join against it; or bound the inner scan with a lower bound and cap the look-back window.
- **Fix side effects:** Changing the semantics of "new" / "returning" artists is user-visible in `js/profile-comparison.js:19-21` ("Новые для вас исполнители", "Снова в вашей музыке"). A lower bound on the look-back would make a long-absent artist look "new" again; the fix must keep the full-history look-back but compute it once.
- **Discovered by:** B

#### F-WX-04-2  [P2] — The same history rows are counted as two different amounts of listening time by the two statistics screens

- **File:** `core/database.py:1736-1746` (`get_wrapped_stats`) vs `services/listening_comparison.py:30-45` (`listening_comparison`)
- **Confirmed:** yes
- **Description:** `get_wrapped_stats` uses `WHEN h.duration_listened > 0 THEN h.duration_listened WHEN t.duration > 0 THEN t.duration ELSE 180.0` — a row with **zero** measured duration is credited with the **full track length**. `listening_comparison` filters the same rows out entirely (`AND duration_listened > 0`). Rows with `duration_listened = 0` are produced by the normal code path: `begin_listening_session` inserts exactly that (`core/database.py:1564`), and it is only overwritten when a heartbeat arrives.
- **Cause:** Two consumers of one table disagree on what a zero-duration row means; the `WHEN t.duration > 0 THEN t.duration` fallback is a legacy of the pre-measurement `log_listening_history` path and was never removed from the Wrapped aggregate.
- **Trigger conditions:** A play that starts but never registers an audible heartbeat (stream error right after `report_state('playing')`, a crash between `begin_listening_session` and the first `_persist_listening`, a track switched immediately). Then "NeDotify Wrapped" on the home page and "Сравнить периоды" on the profile page report different totals for the same day.
- **User impact:** The user's "total listening time" is inflated by full track lengths for plays that never happened, and the two statistics screens visibly disagree.
- **Evidence (measured, 2 rows: one measured 200 s play + one zero-duration row for a 210 s track):**
  ```
  get_wrapped_stats('all'):  total_plays = 2   total_seconds = 410.0
  listening_comparison(week): current plays = 1 current seconds = 200.0
  ```
  ```sql
  -- core/database.py:1738-1742
  COALESCE(SUM(CASE
      WHEN h.duration_listened > 0 THEN h.duration_listened
      WHEN t.duration > 0 THEN t.duration        -- <-- 210 s credited for a 0 s play
      ELSE 180.0
  END), 0) as total_sec
  ```
  ```sql
  -- services/listening_comparison.py:32
  FROM history WHERE played_at >= ? AND played_at < ? AND duration_listened > 0
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wx04_final.py` — inserts the two rows into a throwaway DB and prints both aggregates.
- **Suggested fix:** Decide one semantics for a zero-duration measured row and apply it in both places. The `history` table already has the discriminator column `listening_measured` (`core/database.py:288`, `core/database.py:1564`) — rows created by `begin_listening_session` are `listening_measured = 1`, so they must not fall back to the track length; only legacy rows (`listening_measured = 0`) may.
- **Fix side effects:** Existing users' Wrapped totals will drop (they were inflated). `get_wrapped_stats` is also consumed by `ui/web_new_v2/js/home.js:900`, so the home page numbers change too. A one-time migration would be needed if the totals are to be preserved.
- **Discovered by:** B
- **Owning area:** WN-12 (`core/database.py:1736-1746` — single-file defect); the divergent filter is in WN-25 (`services/listening_comparison.py:32`).

#### F-WX-04-3  [P2] — `media_listened` is written on every heartbeat but read by no user-facing statistic; every screen credits wall-clock time instead of media time

- **File:** `core/api.py:1290-1295` (writes), `core/database.py:1739`, `core/database.py:1847` (read `duration_listened` only), `services/listening_comparison.py:30`, `:36`, `:42`, `:58`, `:69` (read `duration_listened` only)
- **Confirmed:** yes
- **Description:** The session accumulates two measures: `seconds` (wall-clock audibility) and `media_seconds` (wall-clock × playback rate). Both are persisted (`duration_listened` and `media_listened`). **Every** user-facing aggregate reads `duration_listened` and ignores `media_listened`; only `get_recommendation_quality` (`core/database.py:1577`) uses it. So listening at 2× speed is credited with half the time actually consumed, while the `completed` flag on the very same row is computed from `media_seconds` (`core/listening.py:39-41`).
- **Cause:** The schema was extended with the honest media-time column but the aggregates were not migrated to it; there is no single documented definition of "listening time".
- **Trigger conditions:** Any playback with `playbackRate != 1` (the UI exposes a playback-rate control and the player forwards `audio.playbackRate`, `ui/web_new_v2/js/player.js:544`).
- **User impact:** "Время прослушивания" and the period comparison under-report by the speed factor; simultaneously the same row can be flagged `completed = 1` while contributing half the duration — an internally inconsistent record.
- **Evidence:** the repo's own test pins the divergence:
  ```python
  # tests/test_measured_listening.py:109-119  test_double_speed_completion_preserves_wall_time
  api.report_state('playing', listening_session=token)
  api.report_listening_state(token, True, duration_sec=20, playback_rate=2)
  ...
  assert measured['duration_listened'] == 10
  assert measured['media_listened'] == 20
  assert measured['completed'] == 1 and measured['session_finished'] == 1
  ```
  ```python
  # core/listening.py:39-41  -- completion is decided on the OTHER column
  if ended and math.isfinite(duration) and duration > 0:
      self.completed = self.completed or self.media_seconds >= duration * 0.8
  ```
- **Reproduction / verification:** Run `tests/test_measured_listening.py::test_double_speed_completion_preserves_wall_time` (passes today), then observe that `get_wrapped_stats` and `listening_comparison` sum only `duration_listened` — see the `WHERE`/`CASE` clauses quoted above.
- **Suggested fix:** Make one column the canonical "listening time" (prefer `media_listened` where it is present, `duration_listened` as the fallback for legacy rows), and use it in `get_wrapped_stats`, `get_analytics_summary` and `listening_comparison`. Alternatively document `duration_listened` as the canonical wall-clock figure and derive `completed` from it too, so a row cannot say "finished" while its duration says otherwise.
- **Fix side effects:** Existing rows have `media_listened = 0` for pre-migration plays; a `COALESCE(NULLIF(media_listened,0), duration_listened)` fallback (the pattern already used at `core/database.py:1577`) avoids a migration but keeps the two conventions mixed.
- **Discovered by:** B
- **Owning area:** WN-05 (`core/api.py:1290-1295` / `core/listening.py`) and WN-12 (the aggregates).

#### F-WX-04-4  [P2] — The profile page's "listening time" tile is permanently 0: it reads a table that nothing ever writes

- **File:** `core/database.py:2273-2282` (`add_listening_time` / `get_total_listening_time`), `core/api.py:3394` (`get_profile_stats`), `core/api.py:3299` (`get_home_data`), `ui/web_new_v2/js/profile.js:144`
- **Confirmed:** yes
- **Description:** `get_profile_stats` reports `total_listening_time_ms` from `db.get_total_listening_time()`, which sums the `listening_stats` table (`core/database.py:342-348`). **`add_listening_time()` — the only writer of that table — has no caller anywhere in the product** (repo-wide grep: only its own definition; no bridge method, no service, no JS). The table is therefore always empty and the value is always `0`.
- **Cause:** The measured-listening rewrite moved the source of truth to `history.duration_listened` but left the `listening_stats` accumulator and its reader in place; the two were never reconciled.
- **Trigger conditions:** Always — any user opening the profile page.
- **User impact:** The profile page's "Время прослушивания" stat always reads `0`, next to a "Прослушиваний" stat that is populated (that one comes from `get_wrapped_stats('all')`, `ui/web_new_v2/js/profile.js:135-143`). The home dashboard's `total_listening_ms` (`core/api.py:3299-3312`) is zero for the same reason.
- **Evidence:**
  ```python
  # core/database.py:2273-2282 — the writer has no caller
  def add_listening_time(self, duration_ms: int) -> None:
      with self._write_lock:
          with self.conn:
              cursor = self.conn.cursor()
              cursor.execute("INSERT INTO listening_stats (duration_ms) VALUES (?)", (duration_ms,))

  def get_total_listening_time(self) -> int:
      cursor = self.conn.cursor()
      cursor.execute("SELECT COALESCE(SUM(duration_ms), 0) FROM listening_stats")
      return cursor.fetchone()[0]
  ```
  ```js
  // ui/web_new_v2/js/profile.js:144
  text('profile-stat-time', formatListeningTimeShort(profileData.total_listening_time_ms || 0));
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wx04_final.py` prints `listening_stats rows: 0` and `get_total_listening_time() -> 0` on a freshly created database; the repo-wide grep for `add_listening_time` returns exactly one hit — the definition.
- **Suggested fix:** Either delete `listening_stats` + `add_listening_time` + `get_total_listening_time` and compute the tile from `history` (consistent with F-WX-04-2/3), or wire `add_listening_time` into the telemetry chain and keep it as the accumulator.
- **Fix side effects:** The tile will start showing a non-zero number; if the `history`-based value is used, it inherits the semantics question of F-WX-04-2/3.
- **Discovered by:** B
- **Owning area:** WN-12 (`core/database.py:2273-2282` — dead writer + orphaned reader); the consumer is WN-32 (`js/profile.js:144`).

#### F-WX-04-5  [P2] — Privacy: there is no way to delete the listening history, and "clear storage" does not touch it

- **File:** `core/api.py:3105-3154` (`clear_storage`, `_delete_downloaded_files`), `ui/web_new_v2/js/settings.js:226-243`
- **Confirmed:** yes
- **Description:** The listening history is the most personal data the app holds, and **no code path anywhere can remove it.** Exactly what `clear_storage` deletes:

  | action | deletes | does **not** delete |
  |---|---|---|
  | `clear_storage("cache")` | `cache.clear_all()` → the on-disk cover cache, stream cache and temp dirs (`utils/cache_manager.py:152-156`) | everything in SQLite |
  | `clear_storage("all")` | the above **plus the audio files of downloaded tracks** (`os.remove(fp)`, `core/api.py:3138-3154`) | the `tracks` rows, the `is_downloaded` flags, the `history` rows, the `settings` rows |
  | the UI button "Очистить кэш" | calls `clear_storage_cache()` (`core/api.py:4097-4108`) — the cache manager only | `clear_storage("all")` is **never called from the UI**; `tracks`, `history`, `settings` (incl. `session.last_queue`) all survive |

  There is no `clear_history` / `delete_listening_data` bridge method, no SQL that deletes from `history` outside the duplicate-merge migration (`core/database.py:931`) and the `ON DELETE CASCADE` from `delete_track` (`core/database.py:1484-1489`).
- **Cause:** "Storage" in the UI was conceived as disk-cache management; the personal-data store (history, play counts, the persisted queue) was never given a user-facing purge.
- **Trigger conditions:** Any user who wants their listening history gone — the app cannot do it for them; the only way is to delete `~/.nedotify/nedotify_storage.db` by hand.
- **User impact:** The history survives "clear cache" and even "clear storage (all)". A user sharing the machine, or exercising their right to erasure, has no in-app path. The stored data is plaintext SQLite at `~/.nedotify/nedotify_storage.db` (no encryption, no SQLCipher, no key derivation anywhere in `core/database.py`).
- **Evidence:**
  ```python
  # core/api.py:3130-3133
  if storage_type == "all":
      removed = self._delete_downloaded_files()
      logger.info("clear_storage: removed %d downloaded file(s)", removed)
  return True
  ```
  ```js
  // ui/web_new_v2/js/settings.js:231-232
  if (!window.pywebview?.api?.clear_storage_cache) throw new Error('Bridge unavailable');
  const res = await window.pywebview.api.clear_storage_cache();
  ```
- **Reproduction / verification:** Repo-wide grep for `clear_history|delete_history|DELETE FROM history` returns only `core/database.py:931` (the duplicate-merge remap) and `core/database.py:1488` (track delete → CASCADE). Grep of `ui/` for `clear_storage` returns only `clear_storage_cache`.
- **Suggested fix:** Add an explicit, separately-confirmed "Очистить историю прослушивания" action that deletes the `history` rows, resets `tracks.play_count` / `last_played`, clears the `listening_stats` accumulator and the `session.last_queue` settings row — and make `clear_storage("all")` reset `is_downloaded` for the tracks whose files it just removed (today the DB keeps claiming the files exist, so `get_downloaded_tracks()` returns rows whose files are gone).
- **Fix side effects:** Deleting history destroys the taste profile and the Wrapped/comparison statistics irreversibly; it must be an explicit, separately-confirmed action and must not be folded into the existing "clear cache" button, which users expect to be harmless.
- **Discovered by:** B
- **Owning area:** WN-08 (`core/api.py:3105-3154`, `core/api.py:4097-4108`) and WN-32 (`js/settings.js:226-243`); the orphaned `listening_stats` table belongs to WN-12.

#### F-WX-04-6  [P2] — Performance: 722 durable SQLite writes and 2.97 MB of WAL traffic per hour of listening for a single row that is overwritten 720 times

- **File:** `core/api.py:1290-1295` (`_persist_listening`), `core/api.py:1407-1417` (`report_position`), `ui/web_new_v2/js/player.js:611-616`
- **Confirmed:** yes
- **Description:** Every `report_position` heartbeat ends in `_persist_listening` → `db.update_history_duration()` → a full `UPDATE … COMMIT` on the `history` row. Measured over one simulated hour of continuous playback through the real `AppApi`:

  ```
  heartbeats (report_position calls) : 720  (= 0.200/s)
  history rows INSERTed              : 1
  history rows UPDATEd (DB writes)   : 722
  bridge _emit calls (all events)    : 722   (720 x position_changed)
  wall time of the whole chain       : 20.0 ms  (0.028 ms per heartbeat)
  ```

  and on the WAL (`wal_autocheckpoint=0`, so the frames are not recycled):

  ```
  720 heartbeat UPDATEs: 10.6 ms total (15 us/write), WAL grew 2 966 400 bytes (4120 B/write)
  ```

  → **~2.97 MB of WAL traffic per hour of continuous listening** (~71 MB/day), plus 720 SQLite transactions, to update **one column of one row** whose value only needs minute-level accuracy. The CPU cost is negligible (20 ms/hour) — the cost is I/O volume and transaction count, not CPU.
- **Cause:** The measurement accumulator is written through to the database on every heartbeat instead of being batched. `core/settings.py` already implements exactly the right pattern for the same class of problem ("a volume slider drag emits roughly ten set() calls per second" → `FLUSH_INTERVAL_SECONDS = 0.5`, `core/settings.py:290-296`); the telemetry chain does not use it.
- **Trigger conditions:** Any continuous playback. The rate is fixed at 0.2/s by the renderer throttle (`ui/web_new_v2/js/player.js:613`), so it scales with listening time, not with user activity.
- **User impact:** Constant low-level disk writes while the app is idle-but-playing; on a laptop on battery with the app minimized-to-tray, the disk never goes idle. No user-visible latency (15 µs per write), which is why this is P2 and not higher.
- **Evidence:**
  ```python
  # core/api.py:1290-1295
  def _persist_listening(self, session):
      measured = (session.seconds, session.completed, session.media_seconds, session.closed)
      if session.history_id is not None and measured != session.last_saved:
          self._core.db.update_history_duration(session.history_id, session.seconds, session.completed,
                                               media_listened=session.media_seconds, session_finished=session.closed)
          session.last_saved = measured
  ```
  ```python
  # core/database.py:1586-1597 — one UPDATE + COMMIT per heartbeat
  def update_history_duration(self, history_id, duration_sec, completed=False, media_listened=None, session_finished=False):
      with self._write_lock:
          with self.conn:
              ...
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wx04_chain.py` (counts `update_history_duration` calls through the real `AppApi` for one simulated hour) and `%TEMP%\opencode\wx04_bench2.py` (measures the WAL growth per write).
- **Suggested fix:** Keep the accumulator in memory and flush it on a 30–60 s timer plus on every state transition (`playing`/`paused`/`stopped`/`ended`) and on shutdown — i.e. reuse the `core/settings.py` write-behind pattern. Crash exposure rises from ≤5 s to ≤60 s of listening time, which is immaterial for a statistic.
- **Fix side effects:** `flush_listening` (`core/api.py:1297-1302`) currently guarantees the final value is on disk at shutdown; a batched writer must keep that guarantee (`core/settings.py:420-441` `sync_flush_now` is the model). A crash between flushes loses up to one interval of duration, and `completed`/`session_finished` flags would be delayed — `get_recommendation_quality` (`core/database.py:1569-1584`) reads them, so the flush must happen before the session closes.
- **Discovered by:** B
- **Owning area:** WN-05 (`core/api.py:1290-1295`, `core/api.py:1407-1417`).

#### F-WX-04-7  [P2] — Performance: 720 redundant blocking Python→WebView2→JS round trips per hour ship a position the renderer already has

- **File:** `core/api.py:1423-1428` (`_emit("position_changed", …)`), `ui/web_new_v2/js/player.js:609` (local dispatch), `ui/web_new_v2/js/player.js:1925-1932` (`onPositionChanged` early-return), `ui/web_new_v2/js/events.js:110-128`
- **Confirmed:** yes
- **Description:** `report_position` ends with `_emit("position_changed", …)`. On the EdgeChromium/WebView2 backend `evaluate_js` is a **blocking** marshal to the UI thread followed by a wait for the result:
  ```python
  # .venv_win/Lib/site-packages/webview/platforms/edgechromium.py:126-130
  self.webview.Invoke(Func[Object](lambda: self.webview.ExecuteScriptAsync(script).ContinueWith(...)))
  semaphore.acquire()
  ```
  so each heartbeat costs a full round trip into the renderer and back. The payload is **redundant**: the renderer already has the exact position (it computed it), already dispatches the same event locally on every `timeupdate` (`ui/web_new_v2/js/player.js:609`), and the Python-originated handler is a **no-op while playing**:
  ```js
  // ui/web_new_v2/js/player.js:1929-1932
  // If audio is actively playing in HTML5 Audio, let animateProgress handle smooth frame updates
  if (isPlaying && activeAudio && !activeAudio.paused) {
      return;
  }
  ```
  The only consumer of the resulting `nedotify:position_changed` event is the lyrics module (`ui/web_new_v2/js/lyrics.js:304-311`), which already receives the local event 4×/s from `player.js:609`.
- **Cause:** The bridge echoes a value the caller already owns. There is no other Python-side consumer of `position_changed` in the whole product (grep: `_emit("position_changed")` exists only at `core/api.py:1423`).
- **Trigger conditions:** Every 5 s of playback, on the WebView2 UI thread.
- **User impact:** 720 needless UI-thread marshals per hour, each of which also dispatches a DOM `CustomEvent` and runs the lyrics synchroniser — on the thread that must stay responsive for input and animation.
- **Evidence:** measured 720 `position_changed` emits per simulated hour (`%TEMP%\opencode\wx04_chain.py`); the early-return above; `ui/web_new_v2/js/player.js:609`:
  ```js
  // Dispatch locally for lyrics
  document.dispatchEvent(new CustomEvent('nedotify:position_changed', { detail: { pos: currentPosMs, duration: currentDuration } }));
  ```
- **Reproduction / verification:** Grep `_emit("position_changed"` → one hit (`core/api.py:1423`). Grep `position_changed` in `ui/web_new_v2/js` → `events.js:110` (handler), `events.js:117` (re-dispatch), `player.js:609` (local dispatch), `lyrics.js:304` (consumer). Instrument `api._emit` and count (as in `wx04_chain.py`).
- **Suggested fix:** Drop the `_emit` from `report_position` (the frontend already has the position), or keep it only for the non-playing case in which `onPositionChanged` actually does work.
- **Fix side effects:** If any consumer outside `ui/web_new_v2/js` (e.g. a future mini-player or a plugin) relies on the Python-originated event, it would stop receiving it. `ui/web_new_v2/js/lyrics.js` is safe — it consumes the DOM event, which is dispatched locally at 4 Hz regardless.
- **Discovered by:** B
- **Owning area:** WN-05 (`core/api.py:1423-1428`); the redundant local dispatch is WN-29 (`js/player.js:609`).

#### F-WX-04-8  [P2] — Reliability/architecture: the measured listening time is derived from the renderer's `timeupdate` timer, so a throttled renderer silently under-counts playback

- **File:** `core/listening.py:22-30` (`tick`), `core/api.py:1407-1417` (`report_position`), `ui/web_new_v2/js/player.js:580-618` (the only heartbeat source)
- **Confirmed:** code path — yes; exact browser behaviour — **hypothesis** (see below)
- **Description:** `ListeningSession.seconds` only advances when a heartbeat arrives, and the heartbeat arrives **only** from the HTML5 `timeupdate` handler (`ui/web_new_v2/js/player.js:580-617`). The delta per heartbeat is clamped:
  ```python
  # core/listening.py:24-29
  if self.audible and not self.closed:
      # Position heartbeats arrive every 5s. Do not turn a suspended
      # computer or unresponsive renderer into hours of listening.
      delta = max(0.0, min(15.0, now - self.last_tick))
      self.seconds += delta
      self.media_seconds += delta * self.playback_rate
  ```
  The clamp means that if heartbeats arrive **less often** than every 15 s, the credited time is capped at 15 s per heartbeat regardless of how much actually elapsed — the measurement silently under-counts. `report_listening_state` (which carries the "is it audible" truth) is event-driven and fires only on `playing`/`waiting`/`stalled`/`seeking`/`seeked`/`pause`, so it cannot compensate for a missing heartbeat.
  The app is explicitly built for background playback: minimise-to-tray hides the WebView (`core/api.py:926-930` → `self._window.hide()`), the mini-player hides the player UI (`ui/web_new_v2/js/player.js:1359-1361` `isPlayerUiHidden()`), and playback continues. The heartbeat does not.
- **Cause:** The wall-clock measurement is sampled by an event whose cadence is owned by the renderer's timer, rather than being driven by a backend timer (the backend has `time.monotonic()` and a perfectly good place to run one).
- **Trigger conditions:** The window is hidden/minimised or the WebView is occluded long enough for the browser to throttle the media-element timer. **Evidence still missing:** I cannot run the packaged app in this audit (forbidden), so I have not observed the actual `timeupdate` cadence of a hidden WebView2 page. *What would confirm it:* instrument the renderer to log the `timeupdate` interval while the window is hidden, or run the app with the window minimised for 60 s and compare `duration_listened` against the wall clock.
- **User impact (if the hypothesis holds):** Listening with the app in the tray would be credited with a fraction of the real time; the Wrapped/comparison statistics would under-report, and `completed` (computed from `media_seconds`, `core/listening.py:39-41`) would rarely be set for tray listening.
- **Evidence:**
  ```js
  // ui/web_new_v2/js/player.js:580-616 — the ONLY heartbeat producer
  audio.addEventListener('timeupdate', () => {
      if (audio === activeAudio && !isDraggingProgress && !isSeeking) {
          ...
          const now = performance.now();
          if (now - (window._lastReportTime || 0) > 5000) {
              window._lastReportTime = now;
              api('report_position', currentPosMs, currentDuration, 0, currentTrack?.listening_session);
          }
      }
  });
  ```
  Note also that the heartbeat is skipped entirely while the user drags the progress bar (`!isDraggingProgress`) or seeks (`!isSeeking`) — deliberate, but it means the credit for that interval depends on the *next* heartbeat's 15 s clamp.
- **Suggested fix:** Drive the accumulation from a backend-side ticker (the `AppApi` already owns a thread pool and the session objects) instead of from the renderer's event, and treat the renderer heartbeat as a *hint* (position/duration) rather than as the clock. Alternatively send the heartbeat from a `setInterval` in the renderer instead of from `timeupdate`, so it is not tied to the media-event cadence.
- **Fix side effects:** A backend ticker keeps the session alive while the app is idle, so the "user is listening" signal must be cancelled when playback stops — `report_state('paused'/'stopped')` already provides that signal, but a background ticker adds a thread and a wake-up source that must be joined at shutdown (`core/app.py:508-560`).
- **Discovered by:** B
- **Owning area:** WN-05 (`core/api.py:1407-1417`, `core/listening.py:22-30`) / WN-29 (`js/player.js:580-617`).

#### F-WX-04-9  [P3] — Scalability: `history` has no retention policy and three of its consumers are full scans

- **File:** `core/database.py:272-296` (schema + indexes), `core/database.py:1599-1624` (`get_history`), `core/database.py:1836-1860` (`get_analytics_summary`), `core/database.py:1723-1834` (`get_wrapped_stats`), `core/database.py:1484-1489` (`delete_track`)
- **Confirmed:** yes
- **Description:** The table grows by one row per play and is only pruned as a side effect of deleting a track (`ON DELETE CASCADE`). There is **no age-based or size-based retention**. There *is* an index on `played_at` (`core/database.py:286`), so the windowed queries are index-backed — the problem is the queries that are not windowed:
  - `get_analytics_summary()` → `SCAN h` over the whole table + a join per row, always.
  - `get_wrapped_stats('all')` → `WHERE 1=1` → `SCAN h`; called on **every profile page load** (`ui/web_new_v2/js/profile.js:135`).
  - `get_history(50)` → `SCAN t` (all tracks) + an index lookup per track + a temp B-tree sort, i.e. it scales with the *library* size, not with the history size.
  Measured (throwaway DB):
  | rows | `get_wrapped_stats('all')` | `get_analytics_summary()` | `get_history(50)` |
  |---|---|---|---|
  | 10 201 | 14 ms | 1.2 ms | 1.7 ms |
  | 110 201 | 889 ms | 58 ms | 93 ms |
- **Cause:** No retention policy + unbounded aggregate queries on the largest user-generated table.
- **Trigger conditions:** A long-lived install (10 k rows ≈ one year at 30 plays/day; 100 k rows ≈ ten years).
- **User impact:** The profile page takes ~1 s to load its statistics at 100 k rows; the database file grows without bound (~1.6 MB/year of rows — disk is not the problem, query time is).
- **Evidence:**
  ```
  -- get_wrapped_stats('all') totals
  (5, 0, 216, 'SCAN h')
  (7, 0, 45, 'SEARCH t USING INTEGER PRIMARY KEY (rowid=?) LEFT-JOIN')
  -- get_history
  (10, 0, 216, 'SCAN t')
  (12, 0, 61, 'SEARCH h USING INDEX idx_history_track_id (track_id=?)')
  (55, 0, 0, 'USE TEMP B-TREE FOR ORDER BY')
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wx04_bench.py` (10 k and 110 k rows) and `%TEMP%\opencode\wx04_plan.py` (`EXPLAIN QUERY PLAN`).
- **Suggested fix:** Add a retention job (e.g. drop `history` rows older than N years, keeping per-track aggregates in `tracks.play_count`/`last_played` which already exist), and make `get_history` drive off `history(played_at)` with `DISTINCT` instead of scanning `tracks`.
- **Fix side effects:** Retention deletes the raw data the Wrapped/comparison statistics are computed from, so the retention horizon must be at least as long as the longest selectable comparison window (365 days).
- **Discovered by:** B
- **Owning area:** WN-12 (`core/database.py`).

### 3. Clean areas

- **No third-party egress of the listening history.** `services/taste_profile.py` reads the local DB only (its `HISTORY_LIMIT = 1500` cap is a deliberate privacy+cost bound, `services/taste_profile.py:21-22`); Last.fm is used only as a *read* source (`services/recommendation_service.py:498-516`, `services/lastfm_service.py`); there is **no scrobble-out** anywhere — no code posts the user's plays to a third party. The only third-party listener is Discord Rich Presence (`core/services/discord_rpc.py`, WN-26), which sends the *currently playing* track only and is a separate area/opt-in feature.
- **The history table itself carries no artist/title text** — only `track_id`, timestamps and durations (`core/database.py:274-282`); the identifying strings stay in the `tracks` table, so the history table alone is not a readable listening diary.
- **The final session is persisted on every normal exit.** `AppApi.close()` calls `flush_listening()` before destroying the window (`core/api.py:934`); `AppCore.cleanup()` calls it again before `db.close()` (`core/app.py:530-531` → `core/app.py:559-560`); and `main.py`'s post-`webview.start()` block runs `app_core.cleanup()` on window close (`main.py:573-580`). `main.py::on_closed` itself only releases the instance lock (`main.py:406-411`), but the cleanup that follows the webview loop covers it.
- **Crash exposure is bounded.** Because the heartbeat persists the row every 5 s, an unclean exit loses at most ~5 s of accumulated listening time, not the whole session (the row itself is created by `begin_listening_session` at the first audible report, `core/api.py:1323-1327`).
- **One history row per audible play — the de-duplication works.** `maybe_log_history` returns early when `session.history_id is not None` (`core/api.py:1312-1313`), and the repo has regression tests for it (`tests/test_api_f1_audit.py:327-370`).
- **The `_emit` contract is respected.** `_emit` never runs `evaluate_js` on the UI thread (`core/api.py:1147-1154` hands off to an `EmitWorker` thread); the telemetry chain does not violate it. (Note: `evaluate_js` on the WebView2 backend is nonetheless a *blocking* `Invoke` on the UI thread — see F-WX-04-7.)
- **`_window_op_lock` contention is not a practical problem.** All nine other holders of that lock (`core/api.py:731`, `:2236`, `:2253`, `:2256`, `:2985`, `:3006`, `:3466`, `:3481`, `:3484`) hold it for short, non-blocking critical sections; the telemetry critical sections are microseconds long (20 ms of Python work per hour of playback, measured).
- **The windowed comparison queries are index-backed.** `listening_comparison`'s `totals`/`artists`/`daily` queries use `idx_history_played_at` (`services/listening_comparison.py:29-45`) and `get_user_history_tracks` is a `SCAN h USING INDEX idx_history_played_at` with an early-terminating `LIMIT` (`core/database.py:1239-1246`) — both fast. Only the two correlated-subquery queries are the problem (F-WX-04-1).
- **The `listening_session` token handshake is sound.** The token is minted in Python (`core/api.py:1282-1287`), shipped to the renderer in the `track_changed` payload (`core/api.py:1240`), echoed back on every telemetry call (`ui/web_new_v2/js/player.js:543-544`), and stale tokens are rejected (`core/api.py:1359-1360`, `:1409-1410`) — this is what prevents two overlapping plays from mixing into one history row (pinned by `tests/test_measured_listening.py:65-77`).

### 4. Coverage gaps

- **I did not run the packaged app** (forbidden by the audit ground rules), so F-WX-04-8's claim about the renderer's `timeupdate` cadence in a hidden/minimised WebView2 remains a hypothesis: the *code path* is confirmed (the measurement is heartbeat-driven and clamped to 15 s), but the actual throttling behaviour of a hidden WebView2 media element was not observed.
- **No measurement of real user data distributions.** All scan timings come from synthetic histories (uniform 3-year spread, 400 distinct artists, `duration_listened = 200`). A real library has a long tail — popular artists short-circuit the `EXISTS` subquery early, rare artists do not — so real timings for F-WX-04-1 will differ from the table in the finding but stay in the same order of magnitude. The *shape* of the blowup (quadratic) is data-independent.
- **WAL traffic was measured with `wal_autocheckpoint=0`** to make the per-write frame cost visible. With the default checkpointing the WAL file stays small; the 2.97 MB/hour figure is write traffic, not steady-state disk usage.
- **The Windows-only aspects of the DB layer were not exercised**: `core/database.py:179-201` opens a *new connection per thread* (thread-local), so each pywebview bridge thread that writes gets its own connection and its own WAL handle. The cost of connection churn (720 threads/hour ⇒ up to 720 connections/hour on the same file) was not measured; SQLite handles this well, but it is an unmeasured cost of the "one pywebview thread per bridge call" design.
- **I did not review `services/taste_profile.py` in depth** (WN-23) beyond confirming that it reads history locally and caps it at 1 500 rows — its own aggregation cost over a large history was out of scope.
- **The `android/` subtree was not opened**, per the audit brief.
- **The `_emit` payload size / serialisation cost of `position_changed`** (720 × `json.dumps` of a 5-key dict) was not micro-benchmarked; it is negligible next to the UI-thread marshal.

### 5. Architecture improvements (ARCH)

No proven defect — improvement proposals only.

1. **ARCH-1 — Give the telemetry chain one owner instead of three.** Today the *state* lives in the bridge (`core/api.py:354-355`, `_listening_sessions` / `_active_listening_token`), the *measurement* dataclass lives in `core/listening.py` (which explicitly disclaims ownership: *"the caller owns the API's existing lock"*), the *persistence* lives in `core/database.py`, and the *aggregation* lives in `services/listening_comparison.py`. The bridge is the right place for the *command* surface, but not for owning a session object that a service layer and a persistence layer both depend on. A `ListeningSessionStore` in `core/` (owning the sessions, the accumulator and the flush policy, with `AppApi` reduced to a thin adapter) would let the flush policy, the retention policy and the aggregation share one definition of "listening time" — which is the root cause of F-WX-04-2/3/4.

2. **ARCH-2 — Introduce a single canonical "listening time" definition.** Three measures coexist today (`history.duration_listened` = wall time, `history.media_listened` = media time, `listening_stats.duration_ms` = never written) and three consumers each pick a different one. One documented column + one accessor would remove the whole class of F-WX-04-2/3/4.

3. **ARCH-3 — Use the `core/settings.py` write-behind pattern for telemetry.** `core/settings.py:290-296` already solved exactly this problem for a 10-call/s slider. Reusing that shape (in-memory accumulator + interval flush + forced flush at shutdown) would cut 722 writes/hour to ~2/min and make the durability argument explicit in one place.

4. **ARCH-4 — Make the renderer the source of *position*, the backend the source of *time*.** The frontend knows the exact media position and already computes it; the backend knows the wall clock and already owns it. Right now the frontend's position is shipped to the backend and mostly ignored (`core/api.py:1415-1416` uses it only for the duration), while the backend's wall clock is sampled by a frontend event. Splitting the responsibilities explicitly — position from JS, elapsed time from a backend ticker — removes both the redundant round trip (F-WX-04-7) and the renderer-throttling coupling (F-WX-04-8), and would let the backend compute `media_seconds` from real position deltas instead of from `playback_rate` multiplication.

5. **ARCH-5 — Give the personal-data store a lifecycle.** `history`, `tracks.play_count` and `settings.session.last_queue` are personal data with no deletion path (F-WX-04-5) and no retention (F-WX-04-9). A single "private data" module — owning retention, export and erasure — would make the privacy surface auditable in one file instead of being an emergent property of several unrelated tables.

6. **ARCH-6 — Move the "new/returning artist" logic out of correlated subqueries.** F-WX-04-1 is a symptom of expressing a set-difference over artists as a per-row `NOT EXISTS` over the raw event log. A service that owns a materialised artist-activity index (or a small aggregate table maintained by the telemetry writer) would make the comparison a cheap join and would also give F-WX-04-9's retention job something to work with.

7. **ARCH-7 — Remove the dead `_history_logged_key` field.** `core/api.py:1212`, `:1328`, `:1372` write it and nothing ever reads it; the actual de-duplication is `session.history_id is not None` (`core/api.py:1312-1313`). `core/database.py:1331-1337` and `tests/test_api_f1_audit.py:355` describe the field as *the* de-duplication mechanism, which is now misleading documentation of a live contract.
