## WX-04 — Listening telemetry (report_position → listening.py → database.py → listening_comparison.py → UI profile) — ROLE A

### 1. Scope reviewed

**Files opened (path: line ranges actually read)**

| Path | Lines read |
|---|---|
| `docs/audits/WIN_AUDIT_CONTEXT.md` | 1–200 (whole) |
| `docs/audits/WIN_AUDIT_AREAS.md` | 1–70 (whole) |
| `core/listening.py` | 1–44 (whole) |
| `core/api.py` | 330–399, 400–439, 900–969, 1175–1244, 1240–1479, 1480–1629, 1755–1794, 3150–3189, 3285–3324, 3386–3405, 4223–4225 |
| `core/database.py` | 270–314, 338–351, 1250–1379, 1545–1664, 1715–1834, 2275–2294 |
| `core/app.py` | 505–564 |
| `services/listening_comparison.py` | 1–84 (whole) |
| `services/taste_profile.py` | 555–584 |
| `audio/engine.py` | 30–99 |
| `audio/queue.py` | 1–120 |
| `ui/web_new_v2/js/player.js` | 145–164, 500–719, 810–929, 1480–1529, 1600–1699, 2105–2144 |
| `ui/web_new_v2/js/profile.js` | 1–188 (whole) |
| `ui/web_new_v2/js/profile-comparison.js` | 1–56 (whole) |
| `ui/web_new_v2/js/home.js` | 888–927 |
| `ui/web_new_v2/js/queue.js` | 181–182 (grep hit, cited) |
| `ui/web_new_v2/js/utils.js` | 86–104 |
| `ui/web_new_v2/index.html` | 644, 648, 651, 265 (grep hits, cited) |
| `tests/test_measured_listening.py` | 1–128 (whole) |
| `tests/test_listening_comparison.py` | 1–64 (whole) |

**Callees traced into other areas (not re-audited here, named as owners)**

- `core/database.py::get_wrapped_stats` (WN-12) — the "Wrapped" numbers that disagree with the comparison screen.
- `core/database.py::get_total_listening_time` / `listening_stats` (WN-12) — the profile card's source.
- `services/taste_profile.py::_listening_weight` (WN-23) — consumes `history.completed`.
- `core/database.py::get_recommendation_quality` (WN-12) — consumes `history.completed` / `session_finished`.
- `audio/engine.py` / `audio/queue.py` (WN-17) — supply the track dict that carries (or does not carry) `listening_session`.
- `ui/web_new_v2/js/home.js` (WN-31) — renders the Wrapped badge.

**Execution used for verification** (read-only, hermetic, nothing under `~/.nedotify` touched):
`C:\Users\Артур\AppData\Local\Temp\opencode\wx04_check.py` and `wx04_check2.py` run with `& ".venv_win\Scripts\python.exe"`, each with a throwaway SQLite file in `%TEMP%`, a `SettingsStub`, an `EngineStub` and a monkey-patched `time.monotonic`.

---

### 2. Findings

#### F-WX-04-1  [P2] — Re-selecting the currently playing track silently kills the listening session: the rest of the track is not measured and the replay is not recorded as a play

- **File:** `core/api.py:1450-1454`, `core/api.py:1267-1288`, `core/listening.py:9-21`, `ui/web_new_v2/js/player.js:1687-1692`
- **Confirmed:** yes
- **Description:** When the user clicks the track that is already playing (queue drawer, library, search results, profile, home feed), the backend replaces the live `ListeningSession` with a brand-new one whose `audible` flag is `False`, but the frontend does **not** restart the audio, so no `'playing'` event ever arrives to make the new session audible again. Result: (a) the remaining listening time of that track is discarded, (b) the replay is not recorded as a new play (no second history row, `tracks.play_count` not incremented).
- **Cause:** `play_track()` decides "resume vs. new session" from the `listening_session` token carried by the *incoming* track dict. `AppApi._on_track_changed` copies the track (`track_copy = dict(track)`) before stamping the token, and `PlaybackQueue` stores the un-stamped dict, so `get_queue()` never returns a token. The token is therefore missing → `resume` is falsy → `force=True` → `_listening_for_track(..., force=True)` closes the live session and creates a new one with `audible=False`. The frontend's `onTrackChanged` computes `sameTrack = trackPlaybackKey(currentTrack) === trackPlaybackKey(track)` → `true`, and the guard at `player.js:1690` skips `playTrack()`, so the audio keeps playing and no `'playing'` event is emitted. `report_listening_state(..., audible=true)` is only ever sent from the `'playing'` / `'seeked'` / `'ratechange'` handlers, none of which fire — so the new session stays silent forever (`ListeningSession.tick()` accrues only while `self.audible`).
- **Trigger conditions:** play a track, let it run, then click that same track again in the queue drawer (`queue.js:182` → `play_track(track, currentQueue, index)`), in the library (`library.js:247`), in search results, on the profile page or in the home feed — anywhere the click goes through the *multi-track* `play_track(track, list, index)` path. (The single-track path `feature-controls.js:69 play_track(getCurrentTrack())` carries the token and is unaffected.)
- **User impact:** the "time listened" of that track stops growing at the moment of the re-click; the profile/comparison statistics silently under-report; the replay is missing from the play counts and from "Недавно прослушано" counts.
- **Evidence:**
  ```python
  # core/api.py:1450-1454
  if isinstance(track, dict):
      token = track.get('listening_session')
      with self._window_op_lock:
          resume = token and token == self._active_listening_token
      self._listening_for_track(track, force=not resume)
  ```
  ```python
  # core/api.py:1277-1288  (force=True -> old session closed, NEW session created, audible=False)
  else:
      if current:
          current.state(False); current.closed = True
          self._persist_listening(current)
      session = ListeningSession(dict(track))
      sessions[session.token] = session
  ```
  ```javascript
  // ui/web_new_v2/js/player.js:1687-1692  (sameTrack -> playTrack() NOT called -> no 'playing' event)
  } else if (track.stream_url) {
      window._pendingResolveKey = null;
      if (!sameTrack || activeAudio.ended || !activeAudio.src || activeAudio._loadedSourceUrl !== normalizeAudioSourceUrl(track.stream_url)) {
          playTrack(track, track.stream_url);
      }
  ```
- **Reproduction / verification:** hermetic run of `wx04_check2.py` (real `AppApi.play_track`, `EngineStub` queue, fake clock):
  ```
  after 30 s playback : [{'id': 1, 'duration_listened': 30.0, 'completed': 0, 'media_listened': 30.0, 'session_finished': 0}] play_count = 1
  queue entry has token: False
  token after replay  : 4a5ffc06... (old: 461d6f8e...)
  after replay + 30 s : [{'id': 1, 'duration_listened': 30.0, ...}] play_count = 1
  ```
  The row stays at 30.0 s after another 30 s of playback, and no second row is created. Control case (replay *after* the `'ended'` event) correctly produces two rows and `play_count = 2`.
- **Suggested fix:** do not destroy the live session when the incoming track is the same logical track; either carry the `listening_session` token back to the frontend in `get_queue()`/`_on_track_changed` so `resume` can be detected, or make `_listening_for_track(force=True)` adopt the existing session when `_listening_identity` matches, or make the frontend restart the audio (and therefore re-emit `'playing'`) when the user explicitly re-selects the current track.
- **Fix side effects:** adopting the existing session would merge a genuine replay into the previous row (one play instead of two) — the frontend restart is the cleaner fix but changes playback behaviour; carrying the token in the queue payload leaks an internal session id into the UI contract.
- **Discovered by:** A

---

#### F-WX-04-2  [P2] — Two screens show two different "listening time" numbers for the very same window: the Wrapped stats fabricate the full track length for every zero-duration row, the comparison excludes those rows

- **File:** `core/database.py:1736-1746` (Wrapped totals), `core/database.py:1753-1767` (Wrapped top tracks), `services/listening_comparison.py:29-33` (comparison totals), `ui/web_new_v2/js/home.js:908-914`, `ui/web_new_v2/js/profile-comparison.js:15-17`
- **Confirmed:** yes
- **Description:** `get_wrapped_stats()` computes the listening time as `CASE WHEN h.duration_listened > 0 THEN h.duration_listened WHEN t.duration > 0 THEN t.duration ELSE 180.0 END`, i.e. a history row that was measured as **zero** seconds is credited with the *full length of the track* (or a fabricated 3 minutes). `listening_comparison()` filters the same table with `AND duration_listened > 0` and therefore drops those rows. Since `begin_listening_session()` inserts a row with `duration_listened = 0` and only `_persist_listening()` overwrites it later, every play that was skipped inside the first heartbeat (< ~5 s) and every play interrupted by a crash stays at 0 and is inflated by the Wrapped query. The play counts differ for the same reason (`COUNT(h.id)` vs `COUNT(*) … duration_listened > 0`).
- **Cause:** two independent definitions of "listening time" over the same `history` table were never reconciled; the Wrapped query still carries the "fabricated three-minute listen" that `_log_listening_locked` was explicitly written to remove (`core/database.py:1306-1309`).
- **Trigger conditions:** any play shorter than one heartbeat (~5 s), any play interrupted by a kill, and any zero-duration legacy row. The user sees it whenever the home screen's Wrapped badge and the profile's comparison panel are opened for the same period.
- **User impact:** the home badge (`"<N> мин (<M> треков)"`) reports far more listening time than was actually heard; the profile's "Топ треков" list is ordered by the inflated `total_listened_sec`; the comparison panel next to it reports the honest number, so the two screens visibly contradict each other.
- **Evidence:**
  ```sql
  -- core/database.py:1736-1746
  SELECT COUNT(h.id) as total_plays,
         COALESCE(SUM(CASE
              WHEN h.duration_listened > 0 THEN h.duration_listened
              WHEN t.duration > 0 THEN t.duration
              ELSE 180.0
          END), 0) as total_sec
  FROM history h LEFT JOIN tracks t ON h.track_id = t.id
  ```
  ```sql
  -- services/listening_comparison.py:29-33
  SELECT COUNT(*) AS plays, COALESCE(SUM(MAX(0, duration_listened)), 0) AS seconds,
         COUNT(DISTINCT track_id) AS tracks
  FROM history WHERE played_at >= ? AND played_at < ? AND duration_listened > 0
  ```
- **Reproduction / verification:** hermetic run of `wx04_check.py` §5 — one `history` row with `duration_listened = 0` for a 180 s track inside the current 7-day window:
  ```
  wrapped  total_plays=1 total_seconds=180.0
  compare  plays=0 seconds=0.0
  ```
  The same divergence is already pinned as *intended* on the comparison side by `tests/test_listening_comparison.py:21,24` (the `'Silent'` 0-second row is excluded from `current['plays']`).
- **Suggested fix:** make `get_wrapped_stats()` use the same measured-only rule as `listening_comparison()` (`duration_listened > 0`), or make both read a single shared aggregation helper; the `ELSE 180.0` fallback should disappear entirely.
- **Fix side effects:** the home badge and the Wrapped totals will drop for users who currently have many zero-duration rows — an apparent "loss" of history that is in fact the removal of fabricated time. The `plays` count would also shrink unless the play count is separated from the time aggregation.
- **Discovered by:** A

---

#### F-WX-04-3  [P2] — The profile page's "Время прослушивания" card is permanently "0 ч": it reads a table that nothing in the application writes

- **File:** `core/api.py:3388-3397`, `core/database.py:2273-2282`, `ui/web_new_v2/js/profile.js:144`, `ui/web_new_v2/index.html:644`
- **Confirmed:** yes
- **Description:** `get_profile_stats()` returns `total_listening_time_ms` from `DatabaseManager.get_total_listening_time()`, which sums the `listening_stats` table. The only writer of that table is `DatabaseManager.add_listening_time()`, and it has **no caller anywhere in the application** (verified by a recursive search over `core/`, `services/`, `ui/`, `main.py` — the only other writer is the benchmark tool `tools/bench/profile.py`). The table therefore stays empty for every real user and the card always renders `formatListeningTimeShort(0)` → `'0 ч'`.
- **Cause:** the measured-listening rework moved all telemetry into the `history` table but left the profile card pointing at the legacy `listening_stats` accumulator.
- **Trigger conditions:** always, for every user.
- **User impact:** the profile screen shows "Время прослушивания: 0 ч" even after hours of listening, while the comparison panel a few centimetres below shows the real number — the same screen, two contradictory values.
- **Evidence:**
  ```python
  # core/database.py:2279-2282
  def get_total_listening_time(self) -> int:
      cursor = self.conn.cursor()
      cursor.execute("SELECT COALESCE(SUM(duration_ms), 0) FROM listening_stats")
      return cursor.fetchone()[0]
  ```
  ```javascript
  // ui/web_new_v2/js/profile.js:144
  text('profile-stat-time', formatListeningTimeShort(profileData.total_listening_time_ms || 0));
  ```
  ```javascript
  // ui/web_new_v2/js/utils.js:88-89
  export function formatListeningTimeShort(ms) {
      if (!ms || ms <= 0) return '0 ч';
  ```
- **Reproduction / verification:** hermetic run of `wx04_check.py` §6 → `listening_stats rows in a fresh DB: 0`, `get_total_listening_time(): 0`; repo-wide search for `add_listening_time` / `listening_stats` returns only `core/database.py:342/2273/2277/2281` and `tools/bench/profile.py:216`.
- **Suggested fix:** derive the profile card from the same source as the comparison panel (`SUM(duration_listened) FROM history`), or restore a real writer for `listening_stats` from the telemetry chain.
- **Fix side effects:** the card will jump from a constant "0 ч" to a real value — the totals will only cover the period since the measured-listening rework, which may look smaller than the historical total the user expects.
- **Discovered by:** A

---

#### F-WX-04-4  [P2] — `completed` is derived from accumulated media seconds, so a rewind-loop marks a track as fully played and doubles its taste-profile weight

- **File:** `core/listening.py:32-44`, `core/api.py:1332-1353`, `ui/web_new_v2/js/player.js:627-634`, `services/taste_profile.py:556-577`
- **Confirmed:** yes
- **Description:** `ListeningSession.state()` sets `completed` when the track ends and `media_seconds >= duration * 0.8`. `media_seconds` is an **accumulator** (`delta * playback_rate`), not a coverage measure, so it counts the same media twice when the user seeks back. A user who loops the first 40 s of a 3-minute track five times accumulates 150–200 media-seconds, crosses the 80 % threshold and the track is stored as `completed = 1` although most of it was never heard. `UserTasteProfile._listening_weight()` returns `WEIGHT_COMPLETED_PLAY` purely on the `completed` flag (weight 2 per `tests/test_measured_listening.py:93`), so the looped fragment is weighted as a fully played song in the recommendation/taste signal, and `get_recommendation_quality()` counts it under `completions` rather than `skips`.
- **Cause:** the completion test measures *quantity of media consumed* instead of *how much of the track was covered*; the position, which is available (`report_position` receives `pos_ms`), is not used for the test.
- **Trigger conditions:** seeking back and replaying a section (the classic "loop the intro" / "rewind to hear that line again" behaviour), or playing at > 1× speed (media seconds grow faster than wall time, so 2× reaches the threshold in 40 % of the wall time — that part is intended).
- **User impact:** the listening history claims the track was played to the end; the recommendation engine over-weights it; the "completed" statistics are wrong.
- **Evidence:**
  ```python
  # core/listening.py:39-41
  if ended and math.isfinite(duration) and duration > 0:
      # Seeking to the last second does not prove a completed listen.
      self.completed = self.completed or self.media_seconds >= duration * 0.8
  ```
  ```python
  # services/taste_profile.py:557-559
  @classmethod
  def _listening_weight(cls, row) -> float:
      if cls._field(row, 'completed', 0):
          return cls.WEIGHT_COMPLETED_PLAY
  ```
- **Reproduction / verification:** hermetic run of `wx04_check.py` §2 — a 180 s track where only the first 40 s is ever heard, repeated:
  ```
  rewind-loop row : [{'id': 1, 'duration_listened': 150.0, 'completed': 1,
                      'media_listened': 150.0, 'session_finished': 1, 'listening_measured': 1}]
  ```
  150 ≥ 180 × 0.8 = 144 → `completed = 1` although the user never heard past 0:40.
- **Suggested fix:** base the completion test on the *covered* portion of the track (e.g. track the maximum reached position / the furthest contiguous segment, or de-duplicate repeated media), not on the accumulated media seconds; alternatively compare `media_seconds` against the elapsed media span.
- **Fix side effects:** genuinely repeated listening to a whole track (e.g. a user who replays the last chorus) would no longer be counted as `completed`; `WEIGHT_COMPLETED_PLAY` would apply less often, slightly changing the taste profile.
- **Discovered by:** A

---

#### F-WX-04-5  [P3] — Every 5-second heartbeat performs a full UPDATE + WAL commit on the history row and an `_emit` round-trip to the WebView, all while holding the shared window lock

- **File:** `ui/web_new_v2/js/player.js:611-616`, `core/api.py:1407-1428`, `core/api.py:1290-1295`, `core/database.py:1586-1597`
- **Confirmed:** yes
- **Description:** the frontend reports the position at most every 5 s; every such call makes the backend (a) tick the in-memory session, (b) call `_persist_listening()` → `update_history_duration()` → a `BEGIN … UPDATE history … COMMIT` on the user's library database, and (c) `_emit("position_changed", …)` → an `evaluate_js` round-trip into the renderer. The write happens on *every* heartbeat because `measured != session.last_saved` as soon as `session.seconds` changed, and it is executed while `self._window_op_lock` (the same RLock that guards window/mini-player operations) is held.
- **Cause:** `_persist_listening()` is invoked from the hot path (`report_position`) instead of from a throttled/flushed writer, and the "only write when something changed" test compares a value that changes on every tick.
- **Trigger conditions:** any playback — 720 UPDATEs + 720 `_emit` round-trips per hour of listening.
- **User impact:** constant write traffic on `~/.nedotify/nedotify_storage.db`; a write failure inside `report_position` aborts the rest of the call, so `engine._last_reported_position` is not updated for that heartbeat.
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
  ```javascript
  // ui/web_new_v2/js/player.js:611-616
  const now = performance.now();
  if (now - (window._lastReportTime || 0) > 5000) {
      window._lastReportTime = now;
      api('report_position', currentPosMs, currentDuration, 0, currentTrack?.listening_session);
  }
  ```
- **Reproduction / verification:** hermetic run of `wx04_check2.py` §C (spy on `db.update_history_duration`):
  ```
  update_history_duration calls for 60 s of playback: 12
  values written: [5.0, 10.0, 15.0, 20.0, 25.0, 30.0, 35.0, 40.0, 45.0, 50.0, 55.0, 60.0]
  ```
- **Suggested fix:** persist on a coarser schedule (e.g. every 15–30 s) plus on state changes, and keep `flush_listening()` as the final flush; the `position_changed` emit can be dropped when the frontend is the source of the position anyway.
- **Fix side effects:** a crash/kill would then lose up to the throttle interval of listening time instead of ≤ 5 s. The performance angle overlaps with Role B's review of the bridge and the persistence layer.
- **Discovered by:** A

---

#### F-WX-04-6  [P3] — The comparison's per-day series — the only consumer of the timezone offset — is computed by the backend and then dropped by the UI

- **File:** `services/listening_comparison.py:41-45`, `services/listening_comparison.py:25`, `ui/web_new_v2/js/profile-comparison.js:12-23`
- **Confirmed:** yes
- **Description:** `listening_comparison()` runs a third `GROUP BY date(played_at, ?)` query to build `current.daily` / `previous.daily` using the `utc_offset_minutes` modifier, but `profile-comparison.js` never reads `data.current.daily` (it renders three metrics and three artist lists only). No other consumer exists in the tree (`grep -r "\.daily" ui/` matches only `home.js:914`, which is the unrelated `daily_activity` of the Wrapped stats). The whole timezone plumbing is therefore a no-op for the user today.
- **Cause:** the backend produces a richer payload than the view consumes; the view was never finished.
- **Trigger conditions:** always (every comparison request pays for an extra grouped query whose result is discarded).
- **User impact:** the user never sees a per-day breakdown of the comparison, and the offset that the browser supplies has no visible effect — while the panel footer claims "Сравниваем два последовательных периода по 7 дней" with no per-day evidence.
- **Evidence:**
  ```python
  # services/listening_comparison.py:41-45
  daily = [dict(row) for row in db.conn.execute('''
      SELECT date(played_at, ?) AS day, COUNT(*) AS plays, SUM(duration_listened) AS seconds
      FROM history WHERE played_at >= ? AND played_at < ? AND duration_listened > 0
      GROUP BY day ORDER BY day
  ''', (modifier, *bounds))]
  ```
  ```javascript
  // ui/web_new_v2/js/profile-comparison.js:14-19  (metrics + artists only; `daily` never referenced)
  const metrics = [
      ['Время прослушивания', formatListeningTimeShort(data.current.seconds * 1000), ...],
  ```
- **Reproduction / verification:** `grep -rn "\.daily" ui/web_new_v2/js` → only `home.js:914` (`stats.daily_activity`, a different endpoint). `profile-comparison.js` contains no reference to `daily`.
- **Suggested fix:** either render the returned `daily` series in the comparison panel (it is already timezone-correct) or stop computing it.
- **Fix side effects:** rendering it makes the offset load-bearing — the half-day truncation described in F-WX-04-7 becomes user-visible and would need the local-day alignment fixed at the same time.
- **Discovered by:** A

---

#### F-WX-04-7  [P3] — A play is attributed entirely to its START day: `played_at` is the INSERT timestamp, so a long background play is counted in the wrong comparison window

- **File:** `core/database.py:1558-1567`, `core/database.py:274-281`, `services/listening_comparison.py:23-24`, `core/database.py:1727-1734`
- **Confirmed:** yes
- **Description:** `begin_listening_session()` inserts the row with `played_at DEFAULT CURRENT_TIMESTAMP`, i.e. the moment playback *started*. Both the comparison and the Wrapped stats then slice by `played_at`. A play that starts one minute before the window boundary and continues for an hour *inside* the window is counted entirely in the earlier window. The same applies to the day buckets (`date(played_at, …)`) and to the daily-activity chart.
- **Cause:** the history row has a single "played at" timestamp used both as the event time and as the bucket key, while the measured duration may span a window boundary.
- **Trigger conditions:** a track that is played across midnight, or a long track played near the end of the comparison window; more visible for users who leave tracks playing in the background.
- **User impact:** the "current vs previous" comparison can move a sizeable chunk of real listening time into the wrong half; the last day of the chart is always partial and the first day is always truncated.
- **Evidence:**
  ```python
  # core/database.py:1564-1565
  cursor.execute('INSERT INTO history (track_id, duration_listened, completed, listening_measured, recommendation_context) VALUES (?, 0, 0, 1, ?)',
                 (track_id, context))
  ```
  ```python
  # core/database.py:274-281
  CREATE TABLE IF NOT EXISTS history (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      track_id INTEGER NOT NULL,
      played_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
      ...
  ```
- **Reproduction / verification:** reading the code is sufficient (the INSERT is the only place `played_at` is set for measured plays, and it is never updated afterwards — `update_history_duration()` only writes `duration_listened`, `completed`, `media_listened`, `session_finished`).
- **Suggested fix:** store the session end time as well and attribute the measured span to the window(s) it actually covers, or define the comparison windows on local calendar days and split a straddling play.
- **Fix side effects:** a schema migration for the new column; the "plays" counters would need a decision (a play belongs to exactly one window).
- **Discovered by:** A

---

#### F-WX-04-8  [P3] — The "dedup key" of the scenario does not exist: `record_listening_once` is deprecated dead code, `_history_logged_key` is write-only, and the docstring in `database.py` describes a mechanism that is not there

- **File:** `core/database.py:1320-1338`, `core/api.py:1304-1330`, `core/api.py:1212`, `core/api.py:1372`, `core/api.py:1262-1265`
- **Confirmed:** yes
- **Description:** the audit scenario asks for "the dedup key built from `_listening_identity`". In the current code there is no such key:
  - `DatabaseManager.record_listening_once(track_id, dedup_key)` raises `NotImplementedError` and has no caller (it is deliberately deprecated).
  - `_listening_identity()` is **not** a dedup key — it is the predicate used to decide whether an incoming track may reuse an existing `ListeningSession`.
  - The effective dedup is `session.history_id is not None` inside `maybe_log_history()`, i.e. "one history row per `ListeningSession`". A session is closed on a track change, on the `'ended'` event, on `report_state('stopped')` and by `flush_listening()`.
  - `AppApi._history_logged_key` is assigned in three places (`api.py:1212`, `1328`, `1372`) and **never read** — it is dead state, and the docstring at `core/database.py:1330-1332` claims the dedup "lives" in it.
- **Cause:** the persistent dedup was removed (it froze the play counters), the replacement was implemented in the caller, but the documentation in the database layer was not updated.
- **Trigger conditions:** always — this is a maintenance hazard rather than a runtime failure.
- **User impact:** none directly; a future maintainer who trusts the docstring would reintroduce a persistent per-track dedup and re-break the play counters.
- **Evidence:**
  ```python
  # core/database.py:1320-1338
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
  # core/api.py:1310-1313  (the real dedup)
  with self._window_op_lock:
      session = self._listening_for_track(track)
      if session.history_id is not None:
          return
  ```
- **Reproduction / verification:** `grep -rn "record_listening_once" core/ services/ ui/ main.py` → only the definition; `grep -rn "_history_logged_key" core/` → three assignments, no read. The behaviour that the scenario asks about was verified empirically instead (see §3 "Dedup window").
- **Suggested fix:** update the docstring in `database.py` to describe the real mechanism (`ListeningSession` + `history_id`), and delete the dead `_history_logged_key` attribute (or actually use it).
- **Fix side effects:** none (documentation/dead-code cleanup).
- **Discovered by:** A

---

### 3. Clean areas

**Reporting cadence and the delta computation — traced and correct.**

- Cadence: `js/player.js:611-616` reports the position at most every 5000 ms from the `timeupdate` handler (`timeupdate` itself fires ~4 Hz), plus one extra call per `seekTo` (`player.js:850`, which omits the session token — harmless, the backend then applies it to the active session).
- Per call, `core/api.py:1407-1428` does exactly three things: `session.tick()` (in-memory), `_persist_listening()` (one UPDATE on the `history` row, see F-WX-04-5) and `_emit("position_changed", …)`. There is no separate accumulator table.
- **The position is never used for the time accounting.** `ListeningSession.tick()` (`core/listening.py:22-30`) uses `time.monotonic()` deltas only, so a REWIND cannot add listening time beyond the real elapsed wall time. `pos_ms` is used solely for `engine._last_reported_position` and the `position_changed` event.
- The tick is clamped to `min(15.0, now - last_tick)`, which protects against a suspended machine / frozen renderer adding hours of "listening" — a deliberate and correct guard.

**Paused / buffering / seeking / background — not counted, correctly.**

- Pause: the `'pause'` handler (`player.js:620-626`) sends `report_state('paused')` → `session.state(False)` → `audible=False`; `timeupdate` does not fire while paused.
- Buffering: `'stalled'` / `'waiting'` (`player.js:529-538`) send `report_listening_state(token, false)` → `audible=False`.
- Seeking: `'seeking'` (`player.js:562-567`) sets `audible=False`; `'seeked'` (`player.js:568-579`) restores it only when the audio is actually playing (`!audio.paused && readyState >= 3`).
- Background: hiding the window only stops the `requestAnimationFrame` progress loop (`player.js:1489-1500`); the `timeupdate` handler keeps running, and since the accounting is wall-clock based, background playback is counted correctly.
- `pagehide` (`player.js:1502-1504`) reports `audible=False` so a closed window stops accruing.

**Dedup window — correct for the realistic cases (verified by execution).**

- A track played twice in a week produces **two** history rows: the dedup is per `ListeningSession` and there is no persistent per-track key, so there is no window to bound. Verified: `wx04_check2.py` §B → `rows: [id 1, id 2]`, `play_count = 2`.
- A pause/resume of the same track does **not** create a second row (`session.history_id is not None` short-circuits `maybe_log_history`).
- A track switch closes the old session and persists its seconds (`core/api.py:1278-1281`); the pinned regression tests `tests/test_measured_listening.py:65-87` cover this ("re-resolved same track keeps one listening session", "track switch / stale state do not mix history").

**Session lifecycle — no row is left open.**

- `flush_listening()` (`core/api.py:1297-1302`) closes and persists every session and is called from `core/app.py:530-531` (`AppCore.cleanup`) and from `AppApi.close()` (`core/api.py:934`, the non-tray path). The "minimize to tray" path returns before the flush, which is correct because playback continues.
- `session_finished` is set from `session.closed` on every write, so `get_recommendation_quality()` can distinguish a finished session from a killed one. A process killed mid-track leaves at most one heartbeat of stale duration and `session_finished = 0` — no dangling "open" state exists in the schema.

**Timezone — the sign convention is correct on both sides (verified).**

- JS: `profile-comparison.js:33` → `window.pywebview.api.get_listening_comparison(period, -new Date().getTimezoneOffset())`. `getTimezoneOffset()` returns *minutes to add to local time to get UTC*, so for UTC+3 it returns `-180` and the JS sends `+180`.
- Python: `services/listening_comparison.py:25` → `modifier = f'{offset:+d} minutes'` → `date(played_at, '+180 minutes')` shifts the UTC `played_at` **forward** to local time. Verified: a `played_at` of `2026-10-15 21:30:00` UTC buckets as `2026-10-16` with `+180` and as `2026-10-15` with `-180` (so a flipped sign would move every row by 6 h).
- The hard-coded default `utc_offset_minutes=180` (`core/api.py:4223`) is only a fallback: the only UI caller always passes the browser value, and the validation range `-720..840` covers UTC-12..+14.
- Note the offset is applied **only** to the day bucketing, not to the window bounds — see F-WX-04-6 for why that is currently invisible.

**Period boundaries — consistent between the two screens.**

- Comparison: two equal, non-overlapping rolling windows of `now-N days` in UTC: current `[now-7d, now)`, previous `[now-14d, now-7d)` (`listening_comparison.py:22-24`). Not a Monday-based calendar week, not 14 days.
- Wrapped: `datetime('now', '-7 days')` / `'-30 days'` / `'-365 days'` (`core/database.py:1727-1734`) — the same rolling definition, one window only (plus an `'all'` option the comparison does not have).
- The **window** definitions agree; only the *measurement* differs — see F-WX-04-2.

**Comparison maths — no division by zero, no crash on empty history (verified).**

- `percent = round((after - before) / before * 100, 1) if before else None` (`listening_comparison.py:54`) → no `ZeroDivisionError`; the UI maps `null` to "Раньше прослушиваний не было" (`profile-comparison.js:7`).
- Empty history → all zeros, empty lists; the UI shows "За этот период пока нет прослушиваний" / "Пока без новых исполнителей". Verified in `wx04_check.py` §3 and pinned by `tests/test_listening_comparison.py:32-36`.

**UI field names — they match the backend payload exactly.**

`current.{plays,seconds,tracks,top_artists}`, `previous.{…}`, `delta.{plays,seconds,tracks}.{absolute,percent}`, `new_artists`, `returning_artists`, `days` are all consumed by `profile-comparison.js:14-21` with the names the service returns; the `current.daily` series is the only unused field (F-WX-04-6). `formatListeningTimeShort(data.current.seconds * 1000)` correctly converts seconds → ms.

---

### 4. Coverage gaps

- **pywebview is not installed in `.venv_win`** (`import pywebview` → `ModuleNotFoundError`), so I could **not** verify on which thread pywebview dispatches `js_api` calls. Whether the per-heartbeat SQLite write of F-WX-04-5 can block the UI thread is therefore unverified — Role B should check it against the installed pywebview version pinned in `requirements.txt`.
- **The frontend half of F-WX-04-1 is derived by reading, not by running the app.** The backend behaviour (a new, silent session; the lost seconds; the missing play) was confirmed by execution against the real `AppApi.play_track`; the claim that the renderer does not restart the audio (hence no `'playing'` event) comes from `player.js:1625-1692` plus `audio/engine.py:78-99` and `audio/queue.py`. Running the real app was out of scope per the ground rules.
- **WebView2 background behaviour was not measured**: whether `timeupdate` keeps firing at the same rate while the window is hidden/minimised (which decides whether background playback is counted at the full rate or slightly under-counted) depends on the embedded browser, not on the code I could read.
- **The `daily` series may be consumed by a UI build outside this tree**; within this repository nothing reads `data.current.daily`.
- `services/taste_profile.py` was read only around `_listening_weight`; the rest of the taste pipeline (recency factors, `WEIGHT_*` constants) was not audited, so the downstream effect of F-WX-04-4 on the recommendations was not quantified.
- `core/database.py::get_recommendation_quality` and `log_listening_history` / `_log_listening_locked` were read but not exercised end-to-end; the legacy `add_to_history` path (still reachable via `AppApi.maybe_log_history`'s fallback when `begin_listening_session` is missing) was not exercised.
- The `listening_stats` table (F-WX-04-3) may contain rows written by an older build of the app; if so, the profile card would show a stale non-zero total rather than a constant 0 — the "always 0" conclusion holds for a fresh profile only.
