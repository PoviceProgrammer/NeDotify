## AREA WN-24 — Catalog, artist, playlist-import, smart-playlist services — ROLE B

### 1. Scope reviewed

**Files opened (read in full):**

- `services/smart_playlists.py` (1–177, full file)
- `services/catalog_service.py` (1–251, full file)
- `services/artist_service.py` (1–388, full file)
- `services/playlist_import_service.py` (1–345, full file)

**Callers / callees traced (read, not modified):**

- `core/api.py` — `_is_ssrf_safe_url` (161–195), `_dns_resolves_to_public_ip` (133–158), `_extract_first_url` (198–220), `import_external_playlist` (2362–2414), `_smart_playlists` / `get_smart_playlists` / `create_smart_playlist` / `update_smart_playlist` / `delete_smart_playlist` / `get_smart_playlist_tracks` (4192–4217), `_catalog_service` (2234–2242), `get_album_tracks` / `get_album_details` (2244–2265), `get_artists_avatars` (3515–3535)
- `core/database.py` — `tracks` schema (213–241), `stream_cache` schema (309–324), `smart_playlists` schema (414–423), `add_track` (1054–1160), `ensure_track_exists` (1260–1276), `create_playlist_ex` (1867–1890), `add_to_playlist` (1950–1970), `add_tracks_to_playlist` (1972–1999), `get_smart_playlist_tracks` (2001–2002, dead)
- `core/offline.py` (1–77, full file) — `available_tracks` (62–73)
- `core/app.py` — service wiring (120–186): `ArtistService` (134), `PlaylistImportService` (142)
- `core/proxy.py` — `SafeRedirectHandler` / `_safe_urlopen` (368–393) — the in-repo reference implementation of per-hop SSRF validation
- `services/base_service.py` (1–329, full file) — `BaseMusicService`, `_SharedExecutor`, `normalize_proxy_url`
- `services/itunes_gateway.py` (1–93, full file) — `ITunesGateway.get` rate limiter + timeouts
- `services/artist_identity.py` (1–63, full file) — `artist_aliases`, `artist_binding`
- `services/lyrics_service.py` — `LyricsService.__init__` (179–185), `translate_lyrics` (243–272), `HTTP_TIMEOUT` (28)
- `services/youtube_service.py` — `TimeoutSession` (201–213), proxy usage (210/236/359), yt-dlp `socket_timeout` (310, 1092)
- `services/track_resolver.py` — grepped for WN-24 coupling: **no** dependency on catalog/artist/import/smart-playlist services (confirmed clean)
- `utils/cache_manager.py:407-419`, `core/proxy.py:379/841/954/1054` — other `_is_ssrf_safe_url` call sites (context for the guard's contract)
- Tests: `tests/test_smart_playlists.py` (1–137, full), `tests/test_smart_search_bridge.py` (1–45, full), `tests/test_smart_search_ui.py` (1–155, full), `tests/test_catalog_verification.py` (1–169, full), `tests/test_catalog_lyrics_ui.py` (1–83, full)
- UI consumers (read for call shape only, WN-32 scope): `ui/web_new_v2/js/library.js:168-207` (import flow), `:503-528` (smart-playlist paging, calls `get_smart_playlist_tracks(id, 201, offset)`), `ui/web_new_v2/js/smart-playlists.js` (rule editor)
- Library (for external behaviour only): `.venv_win/Lib/site-packages/yt_dlp/networking/_urllib.py:203-218` (redirect handler), `.venv_win/Lib/site-packages/yt_dlp/options.py:616` (`socket_timeout` default `None`), `.venv_win/Lib/site-packages/webview/util.py:234-314` (each bridge call runs in its own thread)

**Empirical verification** (scratch scripts under `%TEMP%\opencode\`, repo untouched): smart-playlist SQL parameterisation, re-import duplication, transaction counts, `EXPLAIN QUERY PLAN` for the smart-playlist and `stream_cache` statements, page-cost benchmarks at 50 000 tracks. `pytest tests/test_smart_playlists.py tests/test_smart_search_bridge.py tests/test_catalog_verification.py -q` → **38 passed**.

---

### 2. Findings

#### F-WN-24-1  [P1] — Playlist import validates only the first URL; yt-dlp's redirect chain is never re-checked (SSRF bypass)

- **File:** `services/playlist_import_service.py:39-58` (dispatch), `:60-71` (`_resolve_youtube`), `:126-136` (`_resolve_soundcloud`); `core/api.py:2364-2367` (the only SSRF check)
- **Confirmed:** yes for the defect (the redirect destination is never validated); hypothesis for the exfiltration variant (see Reproduction)
- **Description:** The bridge validates the URL the user typed, then hands it to `PlaylistImportService.resolve()`, which passes it straight to yt-dlp. yt-dlp installs its own `RedirectHandler` that follows 301/302/303/307/308 to **any** destination — including `http://169.254.169.254/...` (cloud metadata), `http://127.0.0.1:...` or a LAN host. Nothing in the import path re-validates a redirect hop. The repository already contains the correct pattern — `core/proxy.py:368-393` re-runs `_is_ssrf_safe_url` on **every** redirect — but the import path does not use it.
- **Cause:** The security boundary was placed in the caller (`core/api.py`) instead of in the component that performs the fetch, and the component that performs the fetch uses a third-party HTTP client with its own, un-hooked redirect policy.
- **Trigger conditions:** The user pastes a link whose host is public (so it passes `_is_ssrf_safe_url`) and which contains the substring `youtube.com` or `soundcloud.com` anywhere — e.g. `https://attacker.example/youtube.com` (the substring test is at `playlist_import_service.py:50/54`). That host answers `302 Location: http://169.254.169.254/latest/meta-data/iam/security-credentials/`. yt-dlp follows it.
- **User impact:** The app issues a request from the user's machine to an address the app's own policy forbids. yt-dlp's failure text (which embeds the final URL and often part of the response body) is returned verbatim to the UI as `{"success": false, "error": str(exc)}` (`core/api.py:2414`) — a potential read-back channel into the toast shown by `library.js:195`.
- **Evidence:**
  ```python
  # core/api.py:2364-2367  — the ONLY SSRF check in this path
  url = _extract_first_url(url or "")
  if not url or not _is_ssrf_safe_url(url):
      logger.warning("SSRF block triggered for playlist import URL: %s", url)
      return {"success": False, "error": "Некорректная или небезопасная ссылка"}
  ```
  ```python
  # services/playlist_import_service.py:60-71 — no redirect guard, no opener hook
  def _resolve_youtube(self, url: str) -> Dict[str, Any]:
      opts = {"extract_flat": "in_playlist", "skip_download": True, "quiet": True, "no_warnings": True}
      try:
          with self._get_ydl(opts) as ydl:
              info = ydl.extract_info(url, download=False)
  ```
  ```python
  # .venv_win/Lib/site-packages/yt_dlp/networking/_urllib.py:203-218 (library, read-only)
  class RedirectHandler(urllib.request.HTTPRedirectHandler):
      http_error_301 = http_error_303 = http_error_307 = http_error_308 = urllib.request.HTTPRedirectHandler.http_error_302
  ```
  ```python
  # core/proxy.py:379-380 — the pattern the import path is missing
  if not _is_ssrf_safe_url(newurl):
      raise urllib.error.HTTPError(req.full_url, code, f"SSRF blocked redirect destination: {newurl}", headers, fp)
  ```
- **Reproduction / verification:** Static: the only `_is_ssrf_safe_url` call reachable from `import_external_playlist` is `core/api.py:2365`; `PlaylistImportService` contains no reference to it (grep over the file returns nothing) and yt-dlp's redirect handler applies no host policy. Live end-to-end exfiltration was **not** attempted (no external network in this environment) — confirming it requires an attacker-controlled host that 302s to an internal address and a YouTube/SoundCloud-shaped path.
- **Suggested fix:** Validate inside the component that fetches: either resolve the playlist through a guarded opener that re-runs `_is_ssrf_safe_url` on every hop (reuse `SafeRedirectHandler`), or pre-resolve the redirect chain manually with the same guard and refuse any hop that leaves the public space.
- **Fix side effects:** yt-dlp does not expose a per-hop callback cleanly; hooking it may require a custom `RequestHandler`/`RequestDirector` subclass, which is a non-trivial change to a third-party integration. A conservative variant (allow-list the two known hosts) would break legitimate imports of curated third-party mirrors.
- **Discovered by:** B

#### F-WN-24-2  [P2] — Playlist import sets no socket timeout and no entry cap; a slow or huge host hangs the import indefinitely

- **File:** `services/playlist_import_service.py:60-66` (`_resolve_youtube` opts), `:126-131` (`_resolve_soundcloud` opts)
- **Confirmed:** yes
- **Description:** Both yt-dlp option dicts omit `socket_timeout` and any playlist-length cap. yt-dlp's default `socket_timeout` is `None` (`yt_dlp/options.py:616 default=None`), so a TCP connection that never completes blocks the call forever. Every other yt-dlp caller in this repo sets a timeout. There is also no `playlistend`/`playlist_items` limit, so the entire playlist is materialised as a Python list of dicts and then written to the DB.
- **Cause:** `PlaylistImportService` is not a `BaseMusicService` subclass, so it inherits none of the provider conventions (timeout, proxy, bounded worker pool) that the rest of the codebase follows for yt-dlp.
- **Trigger conditions:** (a) The user imports from a host that accepts the connection and then stalls → the import thread parks forever; pywebview runs each bridge call in its own thread (`webview/util.py:308 thread = Thread(target=_call)`), so the thread is never reclaimed and the import modal stays disabled with no feedback (`library.js:177-204`). (b) The user imports a very large playlist (YouTube allows thousands of entries) → unbounded memory + unbounded DB writes.
- **User impact:** The import never completes and never reports an error; the library modal stays locked. In case (b) the user waits minutes with no progress indication and ends up with thousands of rows.
- **Evidence:**
  ```python
  # services/playlist_import_service.py:61-66 — no timeout, no cap
  opts = {
      "extract_flat": "in_playlist",
      "skip_download": True,
      "quiet": True,
      "no_warnings": True,
  }
  ```
  ```python
  # services/playlist_import_service.py:127-131 — same for SoundCloud
  opts = {"extract_flat": "in_playlist", "skip_download": True, "quiet": True}
  ```
  ```python
  # services/youtube_service.py:310 (contrast)   "socket_timeout": 8,
  # services/soundcloud_service.py:249 (contrast) 'socket_timeout': 10,
  # services/vk_service.py:64 (contrast)         'socket_timeout': 10,
  # .venv_win/Lib/site-packages/yt_dlp/options.py:616
  #   dest='socket_timeout', type=float, default=None, metavar='SECONDS',
  ```
- **Reproduction / verification:** grep over `services/` for `socket_timeout` returns hits in `youtube_service.py`, `soundcloud_service.py`, `vk_service.py` — and none in `playlist_import_service.py`. `yt_dlp/options.py:616` confirms the default is `None`.
- **Suggested fix:** Add `socket_timeout` (≈10 s, consistent with `soundcloud_service.py:249`) and `extractor_retries: 1` to both option dicts; add a `playlistend`/entry cap (e.g. 2000) and surface "playlist truncated" to the user; consider running the import on a bounded worker with a wall-clock deadline instead of blocking the bridge thread.
- **Fix side effects:** A short timeout breaks slow-but-valid playlists on bad links; a hard cap silently truncates a legitimately huge playlist, so the cap must be reported in the toast (`library.js:184` already reports `imported_count`).
- **Discovered by:** B

#### F-WN-24-3  [P2] — Re-importing a playlist under the same name duplicates every track in the playlist

- **File:** `core/api.py:2385-2396` (caller), `core/database.py:1867-1890` (`create_playlist_ex`), `core/database.py:1950-1970` (`add_to_playlist`)
- **Confirmed:** yes (reproduced)
- **Description:** `import_external_playlist` creates/reuses the target playlist via `create_playlist_ex`, which **reuses** an existing playlist with the same name (case-insensitive) and returns `created=False`. The import loop then unconditionally inserts every track again. `add_to_playlist` performs a plain `INSERT INTO playlist_tracks` with no existence check, and the table has no `UNIQUE(playlist_id, track_id)` constraint. The result is N copies of every track.
- **Cause:** The "created vs reused" distinction is used only for rollback (`core/api.py:2408-2412`), not for membership de-duplication. The playlist-membership table lacks a uniqueness constraint that would make the insert idempotent.
- **Trigger conditions:** The user imports the same playlist (same resolved name) twice — or imports a playlist whose name collides with an existing one. Because the second import returns `created=False`, the rollback never fires, so even a **failed** second import leaves the duplicates behind.
- **User impact:** The playlist shows every track two or more times; the "N tracks" count in the sidebar is inflated; playback of the duplicate entries repeats the same songs.
- **Evidence:**
  ```python
  # core/api.py:2385-2396
  playlist_id, created = self._core.db.create_playlist_ex(
      playlist_name, f"Imported from {url}"
  )
  added_count = 0
  for track in tracks:
      if not isinstance(track, dict):
          raise ValueError("Resolver вернул некорректную структуру трека")
      track_id = self._core.db.ensure_track_exists(track)
      if not track_id or not self._core.db.add_to_playlist(playlist_id, track_id):
          raise RuntimeError("Не удалось добавить все треки в локальный плейлист")
      added_count += 1
  ```
  ```python
  # core/database.py:1950-1970 — unconditional INSERT, no dedup
  def add_to_playlist(self, playlist_id: int, track_id: int) -> bool:
      ...
      cursor.execute(
          "SELECT COALESCE(MAX(position), 0) + 1 FROM playlist_tracks WHERE playlist_id = ?", (playlist_id,))
      next_pos = row[0] if row else 1
      cursor.execute(
          "INSERT INTO playlist_tracks (playlist_id, track_id, position) VALUES (?, ?, ?)",
          (playlist_id, track_id, next_pos))
  ```
  ```python
  # core/database.py:258-270 — schema has no uniqueness on (playlist_id, track_id)
  CREATE TABLE IF NOT EXISTS playlist_tracks (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      playlist_id INTEGER NOT NULL,
      track_id INTEGER NOT NULL,
      position INTEGER DEFAULT 0, ...)
  ```
- **Reproduction / verification:** Scratch script (`%TEMP%\opencode\wn24_verify.py`), 3-track playlist imported twice under the same name:
  ```
  import #1 ok: True id: 1
  import #2 ok: True id: 1
  playlist_tracks rows: 6 distinct: 3
  get_playlist_tracks len: 6
  ```
- **Suggested fix:** In the import loop, skip tracks already present in the target playlist (or make `add_to_playlist` idempotent with a `UNIQUE(playlist_id, track_id)` index plus `INSERT OR IGNORE`). Decide explicitly whether re-importing the same name should append or replace.
- **Fix side effects:** Adding a `UNIQUE` constraint to an existing table requires a migration that de-duplicates existing rows, which changes the contents of playlists that users have already corrupted by double-importing.
- **Discovered by:** B

#### F-WN-24-4  [P2] — A playlist import performs two write transactions per track, with no cap on the track count

- **File:** `core/api.py:2390-2396`; `core/database.py:1054-1160` (`add_track`), `:1950-1970` (`add_to_playlist`), `:1972-1999` (`add_tracks_to_playlist`, the unused batch path)
- **Confirmed:** yes (transaction counts measured; the batch API exists and is not used)
- **Description:** Each imported track costs two independent SQLite transactions — `ensure_track_exists` → `add_track` (SELECT + INSERT + FTS triggers + COMMIT) and `add_to_playlist` (SELECT MAX(position) + INSERT + UPDATE + COMMIT). There is no upper bound on the number of entries the importer may return, so the number of transactions is entirely attacker/page-controlled.
- **Cause:** The import loop uses the single-item API instead of the existing batch API `DatabaseManager.add_tracks_to_playlist` (`core/database.py:1972`), which performs one `executemany` in one transaction; and the service imposes no entry cap.
- **Trigger conditions:** Importing a large playlist (thousands of entries) — the number of commits scales linearly with the playlist size, all on the single shared WAL connection that the proxy also reads from.
- **User impact:** The bridge promise for the import stays pending for minutes (the modal's submit button stays disabled, `library.js:177-204`); the WAL grows and the proxy's read snapshot is invalidated repeatedly, so playback stutters during the import.
- **Evidence:**
  ```python
  # core/api.py:2390-2396 — one transaction per track, twice
  for track in tracks:
      track_id = self._core.db.ensure_track_exists(track)   # -> add_track -> own transaction
      if not track_id or not self._core.db.add_to_playlist(playlist_id, track_id):  # -> own transaction
          ...
  ```
  ```python
  # core/database.py:1972-1999 — the batch API that already exists and is unused here
  def add_tracks_to_playlist(self, playlist_id: int, track_ids: List[int]) -> int:
      """Batch add tracks to a playlist in a single atomic transaction."""
  ```
- **Reproduction / verification:** Scratch script (`%TEMP%\opencode\wn24_verify.py`), sqlite trace callback on the shared connection, 3-track import:
  ```
  INSERT INTO tracks for a 3-track import: 0     (tracks already existed -> dedup worked)
  INSERT INTO playlist_tracks for a 3-track import: 3
  COMMIT statements for a 3-track import: 4
  ```
  i.e. 4 commits for 3 tracks (1 for `create_playlist_ex` + 3 for `add_to_playlist`) — and 2× that for a fresh set of tracks.
- **Suggested fix:** Collect track ids first, insert them with `add_tracks_to_playlist` in one transaction, and cap the number of imported tracks in `PlaylistImportService.resolve()` (with a user-visible truncation notice).
- **Fix side effects:** A batch transaction holds the write lock for the whole batch, which lengthens the window in which proxy reads are blocked; keep the batch size modest (e.g. 200–500) rather than a single transaction for 5000 tracks.
- **Discovered by:** B

#### F-WN-24-5  [P2] — Every offline smart-playlist page re-scans the whole `stream_cache` table once per 500-track batch

- **File:** `services/smart_playlists.py:156-174` (the `available_only` branch); `core/offline.py:62-73` (`available_tracks`)
- **Confirmed:** yes (measured)
- **Description:** The offline branch of `SmartPlaylistService.tracks()` calls `available_tracks(self.db, batch)` once per 500-row batch. `available_tracks` rebuilds its lookup map from scratch on every call with `SELECT source, source_id, cached_file_path FROM stream_cache WHERE cached_file_path IS NOT NULL` — a **full table scan** of `stream_cache` (there is no index on `cached_file_path`). The offline statement also carries **no `LIMIT`/`OFFSET`** (`services/smart_playlists.py:160`), so the whole ordered matching set is materialised and sorted on every page request.
- **Cause:** A per-batch helper with an unbounded internal query was used from inside a paging loop; the cache map was never hoisted out of the loop or indexed.
- **Trigger conditions:** Offline mode enabled (`is_offline` → `core/api.py:4216`) with a large library. Cost is `ceil(matching_tracks / 500) × stream_cache_rows` row reads **per page**.
- **User impact:** Scrolling a smart collection in offline mode gets progressively slower; the page load competes with the proxy for I/O. Measured: 50 000 tracks / 5 000 `stream_cache` rows → 10 full scans = 50 000 row reads for a single page (141 ms), and it grows linearly from there (100 cached tracks ⇒ 100 scans ⇒ 500 000 row reads).
- **Evidence:**
  ```python
  # services/smart_playlists.py:160-171
  statement = f"SELECT t.* FROM tracks t WHERE {' AND '.join(conditions)} ORDER BY {self.SORTS[rule['sort']]}"
  cursor = self.db.conn.execute(statement, parameters)
  result = []
  available_count = 0
  try:
      while batch := cursor.fetchmany(self.MAX_TRACKS):
          for track in available_tracks(self.db, [dict(row) for row in batch]):
  ```
  ```python
  # core/offline.py:62-64 — full scan, repeated per batch
  def available_tracks(db, tracks):
      cached = {(row['source'], str(row['source_id'])): row['cached_file_path']
                for row in db.conn.execute('SELECT source, source_id, cached_file_path FROM stream_cache WHERE cached_file_path IS NOT NULL')}
  ```
- **Reproduction / verification:** Scratch scripts `%TEMP%\opencode\wn24_verify2.py`, `wn24_verify5.py`, `wn24_verify6.py`:
  ```
  available_tracks() invocations: 10   rows fed in: 5000     (1200-track lib)
  FULL stream_cache scans: 10
  offline page, 50k tracks / 5k stream_cache: 141.0 ms rows=0
  FULL stream_cache scans: 10 ; rows read from stream_cache per page (approx): 50000
  EXPLAIN QUERY PLAN SELECT source, source_id, cached_file_path FROM stream_cache WHERE cached_file_path IS NOT NULL
      SCAN stream_cache
  ```
- **Suggested fix:** Hoist the `stream_cache` map out of the paging loop (build it once per request), and/or add an index on `stream_cache(cached_file_path)`. Consider pushing the availability predicate entirely into SQL and dropping the Python pass.
- **Fix side effects:** Hoisting the map keeps the whole `stream_cache` in memory for the duration of the page (a few MB at 10 k rows) — acceptable but should be bounded.
- **Discovered by:** B

#### F-WN-24-6  [P2] — The artist-avatar lookup has no avatar cache: the documented "cached for a week" does not exist, and the fan-out is unbounded

- **File:** `services/artist_service.py:33-35` (`AVATAR_TTL`), `:46-49` (`_profiles`/`_avatars`/`_avatars_lock`), `:329-339` (`get_avatars`); `core/api.py:3515-3535` (`get_artists_avatars`); `services/catalog_service.py:62-66` (the only TTL that applies)
- **Confirmed:** yes
- **Description:** `ArtistService` declares an avatar cache (`self._avatars`, `self._avatars_lock`) and a one-week TTL (`AVATAR_TTL`) — **all three are dead**: nothing in the repository reads or writes `_avatars`, and `AVATAR_TTL` is referenced only at its own definition. `get_avatars()` therefore re-resolves every artist name through `CatalogService.resolve_artist` on every call; the only caching that applies is `CatalogService._cached`, whose TTL is **900 s** for a hit and **60 s** for a miss. The bridge docstring claims "cached for a week".
- **Cause:** The avatar cache was designed but never wired; `get_avatars` was left to rely on a neighbouring service's much shorter TTL without documenting the dependency.
- **Trigger conditions:** Every home-feed render (`get_artists_avatars` is called from the UI on load). With a cold catalog cache, that is one YouTube-Music artist search **plus** one `get_artist` round trip per artist name — up to 30 names, sequentially, inside a single task.
- **User impact:** The home feed re-issues up to 30 provider round trips every ≤15 minutes instead of every 7 days; on a slow or blocked provider the avatar callback fires very late (or not at all), so the feed renders without avatars. The task occupies **one** of the 8 shared `BaseMusicService` workers (`services/artist_service.py:338 self.submit(task)`) for up to `30 × 8 s = 240 s`, and the iTunes fallback adds up to `30 × 3.5 s ≈ 105 s` of rate-limiter wait (`services/itunes_gateway.py:21 INTERVAL = 3.5`), starving other shared-pool work (e.g. `services/recommendation_service.py:491`).
- **Evidence:**
  ```python
  # services/artist_service.py:33-35 — documented TTL, never used
  #: Resolved avatar URLs live for a week: channel photos change rarely, and the
  #: home feed re-requests the same top artists on every load.
  AVATAR_TTL = 7 * 24 * 3600
  ```
  ```python
  # services/artist_service.py:46-49 — cache and lock declared, never used
  self._profiles: Dict[str, Any] = {}
  self._profiles_lock = threading.Lock()
  self._avatars: Dict[str, Any] = {}
  self._avatars_lock = threading.Lock()
  ```
  ```python
  # services/artist_service.py:329-339 — no local cache at all
  def get_avatars(self, names, callback=None):
      def task():
          mapping = {}
          for name in list(dict.fromkeys(...))[:30]:
              resolved = self.catalog.resolve_artist(name)     # <- every call, no avatar cache
              raw = resolved.get('profile_data') or {}
              mapping[name] = self._best_thumbnail(raw) if resolved.get('status') == 'found' ... else ''
  ```
  ```python
  # services/catalog_service.py:64 — the TTL that actually applies (900 s / 60 s)
  self._results[key] = (time.monotonic() + (900 if result['status'] == 'found' else 60), copy.deepcopy(result))
  ```
  ```python
  # core/api.py:3518 — the false contract
  """Resolve avatar photos for a batch of artist names (home feed).
  One artist-search round trip per unknown name, cached for a week.
  ```
  Repo-wide grep for `_avatars|AVATAR_TTL` finds only the definitions above (plus an unrelated `core/proxy.py::_avatars_root`).
- **Reproduction / verification:** grep over the whole repo for `_avatars` / `AVATAR_TTL` returns only `services/artist_service.py:35,48,49` (and the unrelated `core/proxy.py:131,277`). No write to `_avatars` exists anywhere.
- **Suggested fix:** Either wire the declared avatar cache (`_avatars` + `AVATAR_TTL`) or delete the dead fields and correct the bridge docstring to state the real TTL (900 s). Independently, resolve the names with bounded concurrency and a per-batch deadline instead of 30 sequential 8-second-budgeted lookups on one shared worker.
- **Fix side effects:** A one-week avatar TTL means a changed channel photo is not picked up for a week — that is the documented intent, but it should be surfaced to the user (or shortened to a day).
- **Discovered by:** B

#### F-WN-24-7  [P2] — Playlist import ignores the user's proxy setting; every other provider honours it

- **File:** `services/playlist_import_service.py:26-28` (`__init__` stores `settings`), `:60-71`, `:126-136` (no proxy is ever applied); contrast `services/youtube_service.py:210,236,359`, `services/soundcloud_service.py:165,256,285`, `services/spotify_service.py:107`
- **Confirmed:** yes
- **Description:** `PlaylistImportService.__init__` accepts a `settings` object and never reads it. yt-dlp therefore connects directly, while every other network service in the app applies the user's `auth.proxy_url` through `normalize_proxy_url`.
- **Cause:** `PlaylistImportService` was written outside the `BaseMusicService` provider convention, so it inherited neither the proxy handling nor the shared executor/caching that the convention provides.
- **Trigger conditions:** The user configures a proxy in Settings (required in networks where YouTube/SoundCloud are unreachable) and then imports a playlist.
- **User impact:** Search, streaming and profile lookups work through the proxy, but "Import playlist" fails with a yt-dlp network error — a confusing, inconsistent failure that looks like an outage rather than a missing proxy.
- **Evidence:**
  ```python
  # services/playlist_import_service.py:26-28
  def __init__(self, ydl_factory: Optional[Callable] = None, settings: Any = None):
      self.ydl_factory = ydl_factory
      self.settings = settings            # <- never read again in this file
  ```
  ```python
  # services/youtube_service.py:210 (contrast)
  proxy = normalize_proxy_url(self.settings.get("auth", "proxy_url", "")) if self.settings else ""
  ```
  Repo-wide grep for `proxy_url` in `services/` returns hits in `base_service.py`, `soundcloud_service.py`, `spotify_service.py`, `youtube_service.py` — and none in `playlist_import_service.py`.
- **Reproduction / verification:** grep over `services/playlist_import_service.py` for `proxy` returns nothing; grep over `services/` for `proxy_url` shows the four other call sites listed above.
- **Suggested fix:** Apply the same `normalize_proxy_url(self.settings.get('auth','proxy_url',''))` pattern in `_get_ydl()` (set `proxy` in the yt-dlp options), or make `PlaylistImportService` a `BaseMusicService` subclass and reuse a shared helper.
- **Fix side effects:** `normalize_proxy_url` intentionally ignores an unparseable proxy value and logs a warning — that behaviour must be preserved, otherwise a bad proxy string would break every import with an opaque error.
- **Discovered by:** B

#### F-WN-24-8  [P3] — `PlaylistImportService.resolve()` dispatches on a substring, so a lookalike host is treated as YouTube

- **File:** `services/playlist_import_service.py:46-58`; `:329-337` (plain-text lines become `source='youtube'` tracks)
- **Confirmed:** yes
- **Description:** The provider dispatch is a substring test over the whole string (`"youtube.com" in target`), not a hostname comparison. `https://www.youtube.com.evil.example/list`, `https://attacker.example/?x=youtube.com` and `https://attacker.example/youtube.com` all route into the yt-dlp path. The SSRF guard has already accepted those hosts, so this is not a privilege escalation — but it means the app hands a third-party page to yt-dlp's generic extractor and then persists whatever `id`/`title`/`uploader` it finds as library tracks. Additionally, a non-URL line in an M3U/text playlist becomes a track with `source='youtube'` and `source_id` set to the entire raw line, which is not a valid video id and can never be resolved.
- **Cause:** Ad-hoc string matching instead of `urllib.parse.urlsplit(...).hostname` comparison; the local-file/text parser reuses the `source='youtube'` default for lines it cannot classify.
- **Trigger conditions:** A user pastes a link that merely contains `youtube.com`, or imports a text playlist with free-form lines.
- **User impact:** The library is polluted with rows that can never play (source `youtube`, source_id = a whole line); a crafted page can inject arbitrary "tracks" into the user's library.
- **Evidence:**
  ```python
  # services/playlist_import_service.py:49-55
  # 2. YouTube URL
  if "youtube.com" in target or "youtu.be" in target:
      return self._resolve_youtube(target)
  # 3. SoundCloud URL
  if "soundcloud.com" in target:
      return self._resolve_soundcloud(target)
  ```
  ```python
  # services/playlist_import_service.py:329-337
  elif len(path_or_url) > 2:
      tracks.append({
          "artist": "Unknown Artist", "title": path_or_url.strip(), "album": "Unknown Album",
          "duration": 0.0, "source": "youtube", "source_id": path_or_url.strip(),
      })
  ```
- **Reproduction / verification:** Scratch script: `PlaylistImportService().resolve("http://evil.example.com/playlist.json")` → `PlaylistImportError: Файл плейлиста не найден` (the `.endswith('.json')` branch at line 46 captures it first) — confirming the dispatch order is decided by string shape, not by URL parsing.
- **Suggested fix:** Parse the URL once (`urlsplit`) and compare `hostname` (exact match or a proper registrable-domain check) before dispatching; give unclassifiable text lines `source='local'` or drop them.
- **Fix side effects:** Strict hostname matching rejects legitimate share links that use a non-YouTube host (e.g. `youtu.be` short links, `music.youtube.com` subdomains, regional mirrors) — the allow-list must enumerate them.
- **Discovered by:** B

#### F-WN-24-9  [P3] — `CatalogService._cached` single-flight entry can be poisoned permanently if the owner thread dies with a `BaseException`

- **File:** `services/catalog_service.py:44-70`
- **Confirmed:** yes (code path); trigger probability low
- **Description:** The owner of a single-flight entry removes it from `self._flights` inside a `try/except Exception` block. A `BaseException` (`SystemExit`, `KeyboardInterrupt`, `GeneratorExit`) raised by `fetch()` escapes that handler, so `self._flights[key]` is never popped and `flight['event'].set()` is never called. Every subsequent caller for that key finds `flight is not None`, is therefore not the owner, and waits on an event that will never be signalled — it blocks for the full deadline (8 s) and returns `{'status': 'unavailable'}` **forever**, because no new flight is ever created for that key.
- **Cause:** The flight bookkeeping is not in a `finally:` block.
- **Trigger conditions:** A `BaseException` (or interpreter shutdown) inside `fetch()` — i.e. `fetch()` calls yt-dlp / ytmusicapi / `requests` code that raises something that is not an `Exception`.
- **User impact:** That artist/album lookup is permanently broken for the lifetime of the process (every call waits 8 s and returns "unavailable"), and each such call burns an 8-second wait on the calling thread.
- **Evidence:**
  ```python
  # services/catalog_service.py:49-70
  flight = self._flights.get(key)
  owner = flight is None
  if owner:
      flight = {'event': threading.Event()}
      self._flights[key] = flight
  ...
  try:
      result = fetch()
  except Exception as exc:
      result = {'status': 'unavailable', 'error': str(exc)}
  with self._cache_lock:
      ...
      self._flights.pop(key, None)
      flight['event'].set()
  ```
  There is no `finally:` — the pop + `set()` live inside the `try`'s `except`-sibling block and are skipped when a `BaseException` propagates.
- **Reproduction / verification:** Static reading of the control flow; a live reproduction would require injecting a `BaseException` into `fetch()` (not performed — it would need monkey-patching inside the service's own closure). What would confirm it: `monkeypatch` the ytmusic fake to raise `KeyboardInterrupt` and then assert that the next `resolve_artist` for the same name does not return `unavailable` after 8 s.
- **Suggested fix:** Move `self._flights.pop(key, None)` and `flight['event'].set()` into a `finally:` block, and store an error result for the `BaseException` path so waiters are released immediately.
- **Fix side effects:** None — `finally` also runs on the success path, so the ordering (`result` assigned before `set()`) must be preserved.
- **Discovered by:** B

#### F-WN-24-10  [P3] — Dead, misleading `DatabaseManager.get_smart_playlist_tracks()` duplicates a WN-24 responsibility in the wrong layer

- **File:** `core/database.py:2001-2002`
- **Confirmed:** yes
- **Description:** `DatabaseManager.get_smart_playlist_tracks(playlist_id)` returns `self.get_playlist_tracks(playlist_id)` — i.e. it reads `playlist_tracks` for an id that belongs to the `smart_playlists` table. Smart playlists never have rows in `playlist_tracks`, so this method always returns an empty list. It has **no callers** anywhere in the repo (the live implementation is `SmartPlaylistService.tracks`), yet its name and location invite a future caller to use it and silently get nothing.
- **Cause:** A stub left behind when smart playlists moved into a dedicated service; the DB layer kept a same-named method with different semantics.
- **Trigger conditions:** Any future code that calls `db.get_smart_playlist_tracks(id)`.
- **User impact:** Silent empty results (a smart playlist appears empty) rather than an error.
- **Evidence:**
  ```python
  # core/database.py:2001-2002
  def get_smart_playlist_tracks(self, playlist_id: int) -> List[Dict[str, Any]]:
      return self.get_playlist_tracks(playlist_id)
  ```
  Repo-wide grep for `get_smart_playlist_tracks` returns: this definition, the unrelated bridge method `core/api.py:4214`, and test/UI references to the **bridge** method — no caller of the DB method.
- **Reproduction / verification:** grep (as above); `SmartPlaylistService.tracks` (services/smart_playlists.py:128) is the only implementation that evaluates a rule.
- **Suggested fix:** Delete `DatabaseManager.get_smart_playlist_tracks` (WN-12 owns `core/database.py`; the deletion should be coordinated with that area).
- **Fix side effects:** None — it has no callers.
- **Discovered by:** B

#### F-WN-24-11  [P3] — Every smart-playlist page is a full table scan plus a temp b-tree sort; the offline branch has no `LIMIT` at all

- **File:** `services/smart_playlists.py:128-177` (statements at `:160` and `:176`)
- **Confirmed:** yes (measured and query-plan verified); **impact is currently small** — see User impact
- **Description:** Both statements are `SELECT t.* FROM tracks t WHERE <rule> ORDER BY <sort> LIMIT ? OFFSET ?`. `EXPLAIN QUERY PLAN` shows `SCAN t` + `USE TEMP B-TREE FOR ORDER BY` for every sort variant (the `t.id` tiebreaker and the `COLLATE NOCASE` title sort cannot be served by any existing index), so SQLite materialises and sorts the whole matching set before applying `LIMIT`/`OFFSET`. The offline branch's statement (`:160`) has **no `LIMIT`/`OFFSET`** at all and additionally runs a correlated `EXISTS` subquery per row against `stream_cache`.
- **Cause:** No composite index covers the smart-playlist predicates plus the sort order; the offline variant re-implements paging in Python because the SQL-level row count is not known in advance.
- **Trigger conditions:** Every smart-collection page (the UI requests `get_smart_playlist_tracks(id, 201, offset)` — `ui/web_new_v2/js/library.js:528`). Deep offsets are allowed up to 100 000 (`services/smart_playlists.py:132`).
- **User impact:** **Measured and acceptable at the tested scale** — on a synthetic 50 000-track library: first page 6–8 ms, deep offset (40 000) ≈52 ms, offline page ≈141 ms (see F-WN-24-5 for the offline component). This is a linear, not quadratic, cost and is not currently a user-visible problem; it is reported so the ceiling is known (≈50 ms/page at 50 k tracks, growing linearly).
- **Evidence:**
  ```
  EXPLAIN QUERY PLAN (newest):  SCAN t USING INDEX idx_tracks_added_at
                                USE TEMP B-TREE FOR LAST TERM OF ORDER BY
  EXPLAIN QUERY PLAN (title):   SCAN t
                                USE TEMP B-TREE FOR ORDER BY
  EXPLAIN QUERY PLAN (offline): SCAN t USING INDEX idx_tracks_added_at
                                CORRELATED SCALAR SUBQUERY 1
                                SEARCH sc USING INDEX sqlite_autoindex_stream_cache_1 (source=? AND source_id=?)
                                USE TEMP B-TREE FOR LAST TERM OF ORDER BY
  ```
  ```python
  # services/smart_playlists.py:160 — no LIMIT/OFFSET in the offline branch
  statement = f"SELECT t.* FROM tracks t WHERE {' AND '.join(conditions)} ORDER BY {self.SORTS[rule['sort']]}"
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wn24_verify3.py` (query plans) and `%TEMP%\opencode\wn24_verify4.py` (timings on 50 000 rows): `newest page 0 → 7.9 ms`, `newest page 40000 → 51.4 ms`, `title sort page 0 → 6.7 ms`, `title sort page 40000 → 52.2 ms`, `artist LIKE page 0 → 5.8 ms`.
- **Suggested fix:** No urgent action. If the library grows past ~100 k tracks, add a composite index matching the most common rule+sort pair and cap the maximum `offset` (100 000 currently) with keyset pagination in the UI.
- **Fix side effects:** A new composite index slows every `tracks` insert slightly and must be created by a migration (`core/database.py` owns migrations — WN-12).
- **Discovered by:** B

---

### 3. Clean areas

- **SQL injection in `services/smart_playlists.py` — DISPROVEN (checked exhaustively, as instructed).** The rule never reaches the SQL text:
  - Rule **keys** are allow-listed: `services/smart_playlists.py:24-26` (`allowed = {"added_within_days","not_played_days","favorite","downloaded","unplayed","artist","sort"}`; anything else raises `ValueError`).
  - The **operator** is not user-selectable at all: `normalize_rule` has no operator field, so there is nothing to validate; the comparison shapes are hard-coded (`= ?`, `LIKE ? ESCAPE '\'`, `datetime('now', ?)`).
  - The **column names** are hard-coded tuples, never user input: `services/smart_playlists.py:146` `(("favorite","is_favorite"),("downloaded","is_downloaded"))`.
  - The **ORDER BY fragment** comes from the `SORTS` dict, and the key is validated against it before use: `services/smart_playlists.py:45-47` (`sort not in cls.SORTS → ValueError`), `:160`/`:176` (`self.SORTS[rule['sort']]`).
  - Every **value** is a bound parameter: `:141-142` (`datetime('now', ?)` + `f"-{rule['added_within_days']} days"` where the value is `type(value) is int` and 1..3650 — so the f-string can only ever produce `-<digits> days`); `:148-149`; `:153-155` (the `artist` value is a `str` ≤160 chars, bound with `?`, with `%`, `_` and `\` escaped for the `LIKE ... ESCAPE '\'` wildcard).
  - The rule is re-validated on the **read** path too (`_definition` → `normalize_rule`, `services/smart_playlists.py:71-76`), so a tampered `rule_json` row cannot inject either.
  - Empirical proof (`%TEMP%\opencode\wn24_verify.py`): the rule `{"artist": "Robert'); DROP TABLE tracks;--"}` produced
    `SELECT t.* FROM tracks t WHERE ... AND t.artist LIKE '%Robert''); DROP TABLE tracks;--%' ESCAPE '\' ORDER BY t.added_at DESC, t.id DESC LIMIT 500 OFFSET 0` — the payload is a **bound string**, `tracks` and `smart_playlists` still exist, 0 rows leaked. Payloads `' OR 1=1 --`, `x'; DROP TABLE tracks; --`, `%`, `_`, `\` all returned 0 rows without touching the schema. `{"sort": "title; DROP TABLE tracks"}` and `{"sql": "1=1"}` are rejected with `ValueError`. The existing test `tests/test_smart_playlists.py:70-78` independently pins this.
- **`file://` / UNC / localhost are blocked on the import path.** `_is_ssrf_safe_url` (`core/api.py:161-195`) requires the scheme to be `http`/`https`, so `file://`, `\\server\share`, `C:\...` and `localhost` are rejected before `PlaylistImportService` is reached; `PlaylistImportService.resolve()`'s local-file branch is therefore unreachable from the bridge (the only caller). The local-file branch itself is not a vulnerability but it *is* an unauthenticated arbitrary-file read **if the service is ever called directly** — see ARCH-3.
- **No recursive/self-referencing playlist import.** `PlaylistImportService.resolve()` dispatches to exactly one of `_resolve_youtube` / `_resolve_soundcloud` / `_resolve_local_file`; none of them calls back into `resolve()`. An M3U line that points at another playlist is stored as a *track*, not resolved (`services/playlist_import_service.py:293-318`). There is no recursion and therefore no unbounded depth.
- **Provider failures are isolated in `CatalogService`.** Every provider call is wrapped: `services/catalog_service.py:34-42` (`_call` → `CatalogueUnavailable` on deadline/timeout), `:60-61` (any exception → `{'status':'unavailable'}`), `:84-85`/`:98-99` (YT failure → iTunes fallback → `failed` flag), `:125-129` (a 404 from `get_artist` degrades to candidate lookup instead of raising), `:164-165`/`:181-188`/`:299-300`/`:312-313` in `artist_service.py` (each album/search/playlist fetch degrades to a logged debug and continues). A dead provider degrades the artist/album view; it does not raise into the caller. `tests/test_catalog_verification.py:61-72` pins "network failure is not cached".
- **Timeouts are applied to every outbound call in the catalog/artist path.** `CatalogService` bounds every provider call by an 8-second deadline (`services/catalog_service.py:104`, `:155`, `:169`) and runs them on a dedicated 4-worker pool (`:14-15`) so a hanging provider cannot starve the shared executor. `ITunesGateway.get` applies `timeout=min(timeout, deadline-now)` and a global 3.5 s / 18-per-minute rate limiter (`services/itunes_gateway.py:21-22, 64`). The YTMusic client uses a `TimeoutSession` forcing `timeout=6` (`services/youtube_service.py:201-213`). The bio translation uses `HTTP_TIMEOUT = 6.0` (`services/lyrics_service.py:28, 266`).
- **Smart-playlist persistence is parameterised and bounded.** All writes use bound parameters (`services/smart_playlists.py:99-103`, `:112-118`, `:125`); the playlist count is capped at 100 (`:96-98`, `MAX_PLAYLISTS`); the page size is capped at 500 and the offset at 100 000 (`:130-133`); `bool` is rejected for integer fields (`type(value) is not int`, so `True` is refused — pinned by `tests/test_smart_playlists.py:57-68`); a corrupt `rule_json` row is skipped instead of breaking the list (`services/smart_playlists.py:85-88`, pinned by `tests/test_smart_playlists.py:92-98`).
- **The offline paging logic is correct** even though it is slow (F-WN-24-5): the `available_only` path counts *available* tracks so `offset`/`limit` refer to the filtered set, and it crosses batch boundaries correctly (`services/smart_playlists.py:164-174`; pinned by `tests/test_smart_playlists.py:101-137`).
- **`CatalogService` single-flight is sound in the normal path.** `services/catalog_service.py:44-70`: concurrent callers for the same key share one fetch, the result is published before the event is set, waiters honour the deadline, and only `found`/`not_found` are cached (network failures are not — `tests/test_catalog_verification.py:61-72`). (The `BaseException` hole is F-WN-24-9.)
- **Album/artist identity verification is conservative.** `album_details` refuses to claim an album for a different artist or a mismatching title (`services/catalog_service.py:201-202`, `:234-237`), tracks belonging to another collection are dropped (`:205`), and the YouTube path refuses a non-`MPRE` browse id (`:222-223`). `credited_to` prefers an exact channel-id match and falls back to alias-aware name matching (`services/catalog_service.py:18-23`).
- **`services/track_resolver.py` has no coupling to WN-24** — grep for `catalog|artist|import|smart` returns no service dependency, so a defect in this area cannot corrupt the stream-resolution path.

---

### 4. Coverage gaps

- **No live network tests were run.** The end-to-end exploitability of F-WN-24-1 (an attacker host that 302s to `169.254.169.254` or `127.0.0.1`) was **not** demonstrated: this environment has no outbound internet access and no cloud metadata endpoint. What is confirmed is the *absence of redirect validation* and that yt-dlp follows redirects unconditionally; what remains unproven is whether a real redirect chain plus the error-message echo yields readable content.
- **The iTunes fallback path was exercised only through stubs.** `ITunesGateway.get` was monkey-patched in `tests/test_catalog_verification.py:33`; the real rate limiter, retry-after handling and the `PER_MINUTE = 18` ceiling were read but not driven against the live API.
- **ytmusicapi behaviour was not exercised live.** `get_artist`, `get_artist_albums` (the continuation parser that the code comments at `services/artist_service.py:158-163` say raises `KeyError` on `musicCarouselShelfRenderer`) and `get_album` were only read. The discography-completeness fallback chain (`_collect_albums` → `_search_albums_by_artist`) was therefore validated by reading, not by running.
- **The scale numbers in F-WN-24-11 and F-WN-24-5 come from a synthetic 50 000-row library**, not from a real user's `~/.nedotify` database. The row shape matches the schema, but a real library has FTS triggers, `history` rows and a populated `stream_cache`, so real-world numbers will be somewhat worse.
- **The 240 s worst case for `get_avatars` is a derived bound**, not a measurement: 30 names × the 8 s `CatalogService` deadline (`services/catalog_service.py:104`) plus 30 × 3.5 s of `ITunesGateway` rate limiting. The individual bounds are read from the code; the combination was not timed.
- **Browser-side behaviour was not executed.** The import modal's "stuck button" description (`ui/web_new_v2/js/library.js:177-204`) and the smart-collection paging behaviour were verified by reading the JS and by the node-based test `tests/test_smart_search_ui.py:112-144`, not by driving the real UI.
- **`PlaylistImportService` was not exercised against a real yt-dlp server**, so the exact entry-count ceiling of a large YouTube playlist (and therefore the worst-case transaction count in F-WN-24-4) is an estimate.
- **The `_ssrf_cache` fail-open and DNS-rebinding window were deliberately not filed here.** `core/api.py:152-155` (resolution failure ⇒ verdict stays `True`) and the 120 s DNS-verdict memoisation (`:99`) are defects of the SSRF guard itself, which is owned by **WN-03** (`core/api.py` L1–520). They weaken the only protection the playlist import has, but the root cause is not in WN-24, so they are not double-reported here.

---

### 5. Architecture improvements (ARCH)

**ARCH-1 — `BaseMusicService` is a provider contract being used as a "worker + cache" mixin.**
`services/base_service.py:320-329` declares `search()` / `get_stream_url()` as the provider contract, but `CatalogService` (`services/catalog_service.py:26`) and `ArtistService` (`services/artist_service.py:38`) extend it without implementing either method; they use only `submit()` (the shared 8-worker pool) and `_cache_lock`. Neither uses the shared `_search_cache`/`_stream_cache` that the base class provides, and both open their own caches (`CatalogService._results`/`_flights` under the inherited `_cache_lock` — compliant; `ArtistService._profiles`/`_profiles_lock`/`_avatars`/`_avatars_lock` — two extra locks). *Direction:* split the base class into a provider interface and a `BackgroundWorker`/`CacheHolder` mixin, and let `CatalogService`/`ArtistService` inherit only the latter. This would also remove the temptation to reach for `BaseMusicService` merely to get `submit()`. (The lock rule in `AGENTS.md` — "a new shared field joins its class's existing lock" — is satisfied by `CatalogService`; `ArtistService`'s two extra locks are defensible only because `_cache_lock` is a *class-level* lock shared by every provider, so a per-class lock is the right call there.)

**ARCH-2 — The SSRF guard is a caller-side convention instead of a component contract.**
`_is_ssrf_safe_url` lives in `core/api.py` and is applied by `core/proxy.py` (via an import) and by `utils/cache_manager.py:407`, but the component that actually performs the playlist fetch (`PlaylistImportService`) has no access to it and no defence of its own. `core/proxy.py` even solved the redirect problem properly (`SafeRedirectHandler`). *Direction:* move the guard into a small shared module (`utils/url_safety.py` already exists for URL helpers) and give every outbound component a mandatory "fetch through a guarded opener" entry point, so a new caller cannot forget the check.

**ARCH-3 — `PlaylistImportService.resolve()` has two entirely different trust models in one method.**
The same public entry point accepts (a) a local filesystem path and (b) a remote URL, with the decision made by `os.path.exists()` / a `.endswith()` suffix test (`services/playlist_import_service.py:46`). The local branch reads an arbitrary file with `f.read()` (no size cap) and parses it as JSON/M3U. Today only the bridge calls it, and the bridge's SSRF check makes the local branch unreachable — but the *service* does not enforce that, so the next caller (a plugin, a new bridge method, a CLI) would silently gain arbitrary local-file read. *Direction:* split into `resolve_url()` (network, guarded) and `resolve_file()` (explicitly local, with a size cap and an extension allow-list), so the trust level is visible in the type of the call.

**ARCH-4 — `credited_to` is in the wrong module.**
`services/catalog_service.py:18-23` defines a pure function with no catalogue state, used only by `ArtistService` (`services/artist_service.py:140, 188, 296`) and by `tests/test_catalog_verification.py:76-78`. Its natural home is `services/music_matching.py`, which already owns `artist_matches`/`similarity` — the two functions `credited_to` delegates to. Placing it in `catalog_service.py` makes `ArtistService` import `catalog_service` for a matching helper and drags the whole catalogue module (and its `_catalog_pool` module-level thread pool) into the import graph of a pure utility. *Direction:* move `credited_to` to `services/music_matching.py` (WN-18 owns that module — coordinate with that area).

**ARCH-5 — The smart-playlist service is the only WN-24 service that talks to the DB directly.**
`SmartPlaylistService` holds `self.db` and issues raw SQL (`services/smart_playlists.py:79-177`), including the `smart_playlists` table it owns, while `core/database.py` also exposes a (dead) `get_smart_playlist_tracks` (`core/database.py:2001`). Everything else in WN-24 is a provider client. *Direction:* pick one owner for the `smart_playlists` table — either keep the service and delete the DB stub, or move the SQL into `core/database.py` and keep the service as a rule evaluator. The current split means the schema and its queries live in two layers with the same name.

**ARCH-6 — Layering inversion: `services/` imports from `core/`.**
`services/smart_playlists.py:157` does `from core.offline import available_tracks` — a service-layer module depending on the application-core layer (which itself imports `services/`). *Direction:* move the availability predicate into a neutral module (e.g. `services/availability.py` or `utils/`) that both `core/offline.py` and the smart-playlist service can import, and have `core/offline.py` re-export it.

**ARCH-7 — The playlist import duplicates the provider plumbing instead of reusing it.**
`PlaylistImportService` re-implements yt-dlp option construction, proxy handling (missing, F-WN-24-7), timeouts (missing, F-WN-24-2) and error wrapping, while `services/youtube_service.py:253+`, `services/soundcloud_service.py:239+` and `services/vk_service.py:64` already contain the tuned yt-dlp option sets. *Direction:* extract one `yt_dlp_options(settings, *, extract_flat)` helper and have all four call sites use it — that alone fixes F-WN-24-2 and F-WN-24-7 in one place.

**ARCH-8 — `ArtistService` builds its own catalogue identity instead of consuming `CatalogService`'s.**
`ArtistService._collect_albums`/`_collect_tracks` issue their own `yt.get_artist_albums` / `yt.search` / `yt.get_playlist` / `yt.get_album` calls (`services/artist_service.py:133-317`), while `CatalogService.album_details` already knows how to resolve an album and its track list (`services/catalog_service.py:168-251`). The two produce the same album dict shape by different routes. *Direction:* let `ArtistService` ask `CatalogService` for album details instead of re-implementing the album lookup, and keep only the artist-level fan-out in `ArtistService`.

**ARCH-9 — Cache TTLs and cache stores are scattered and one is a lie.**
Four different TTLs govern artist data: `CatalogService` 900 s / 60 s (`services/catalog_service.py:64`), `ArtistService.PROFILE_TTL` 900 s (`services/artist_service.py:31`), the declared-but-unused `AVATAR_TTL` 7 d (`:35`), and `ITunesGateway` 900 s / 60 s (`services/itunes_gateway.py:78`). `ArtistService` also mixes clocks (`time.time()` at `:70/:79` vs `time.monotonic()` in `CatalogService` at `:47/:64`). *Direction:* one cache module with one clock and one TTL vocabulary.

**ARCH-10 — Testability gaps in the WN-24 test files.**
`tests/test_smart_playlists.py` pins the rule allow-list, the literal-`artist` behaviour (`test_artist_values_are_literal_and_cannot_change_sql`, lines 70-78 — the strongest existing guard against SQL injection), the pagination bounds and the offline paging. `tests/test_smart_search_bridge.py` pins the bridge round-trip and the offline bridge filter. `tests/test_catalog_verification.py` pins identity resolution, the "no-match is cached but network failure is not" contract, and album verification. `tests/test_catalog_lyrics_ui.py` and `tests/test_smart_search_ui.py` are JS-side tests (out-of-process) that pin event names, request-id matching and page bounds.
*Missing:* (a) no test asserts that `PlaylistImportService` never issues a request to a non-YouTube/SoundCloud host, nor that a redirect target is re-validated (F-WN-24-1); (b) no test asserts that the import is idempotent for a repeated import of the same playlist name (F-WN-24-3); (c) no test asserts a cap on the number of imported entries or on the number of write transactions (F-WN-24-2/F-WN-24-4); (d) no test asserts that the import honours `auth.proxy_url` (F-WN-24-7); (e) no test asserts that a provider failure in `CatalogService` leaves the *caller* (`AppApi.get_album_details`) alive — `tests/test_catalog_verification.py:158-169` covers request-id supersession, not failure isolation; (f) no test asserts that `get_avatars` is bounded in time or in provider calls (F-WN-24-6); (g) `PlaylistImportService` has **no dedicated test file at all** — repo-wide grep shows the only references are `core/app.py:142`, `core/api.py:2372`, `tools/bench/pyprof_child.py:241` and `tests/test_api_f1_audit.py:290,306`.
