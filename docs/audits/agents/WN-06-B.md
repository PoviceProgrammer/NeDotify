## AREA WN-06 — Bridge search, catalog, library listing, favorites, downloads listing — ROLE B

### 1. Scope reviewed

**Files opened (path: line ranges actually read):**

- `core/api.py` — 1–30, 90–269 (SSRF guard / `_extract_first_url` / secret masking), 330–530 (`AppApi.__init__`, `_install_bridge_error_logging`, `cleanup`, `_offline_bridge_result`), 720–770 (`_deferred_window_op`, `_on_window_ui_thread`), 1110–1189 (`_emit`), 1200–1239, 2060–2508 (**WN-06 primary range 2077–2362**, plus `import_external_playlist` body 2362–2415 and `export_playlist` 2416–2496 for context), 2640–2769 (**WN-06 primary range 2727–2733**, plus `_auto_save_favorite` 2640–2725 for context), 3620–3709, 4110–4169
- `services/base_service.py` — 1–329 (full)
- `services/track_resolver.py` — 1–476 (full)
- `services/catalog_service.py` — 1–251 (full)
- `services/youtube_service.py` — 360–639
- `services/soundcloud_service.py` — 100–499
- `services/spotify_service.py` — 1–244
- `services/yandex_service.py` — 85–164
- `services/recommendation_service.py` — 50–89
- `services/artist_service.py` — 38–390 (grep-level)
- `services/playlist_import_service.py` — 1–345 (full)
- `core/database.py` — 210–269 (schema), 350–380 (indexes/migrations), 1054–1419 (`add_track`, `get_all_tracks`, `get_favorite_tracks`, `ensure_track_exists`, `mark_track_downloaded`, `get_downloaded_tracks`, `search_tracks`), 1420–1495 (`search_albums`/`search_playlists`/`get_album_tracks`), 2290–2370 (`download_queue` schema, `download_queue_add`)
- `core/downloader.py` — 27, 340–469 (`queue_download`), 470–662 (`_download_spotify_track`, `_fetch_from_provider`), 664–877 (`_fetch_with_retry`, `_download_worker`, `_execute_download_worker`, `mark_track_downloaded` call site)
- `core/proxy.py` — 23–24, 238–303 (`_safe_stream_local_path`, `_safe_avatar_path`, `_safe_cover_path`)
- `core/offline.py` — 1–77 (full)
- `core/app.py` — 95–291 (AppCore attribute set)
- `core/settings.py` — 300–420 (in-memory settings cache)
- `utils/url_safety.py` — 1–37 (full)
- `utils/search_query.py` — 1–101 (full)
- `ui/web_new_v2/js/search.js` — 75–204, 280–459, 525–593, 595–704, 750–784, 1070–1139
- `ui/web_new_v2/js/library.js` — 320–439, 480–599
- `ui/web_new_v2/js/library-view.js` — 110–190
- `ui/web_new_v2/js/home.js` — 140–199
- `ui/web_new_v2/js/events.js` — 100–179, 210–284
- `ui/web_new_v2/js/main.js` — 95–134
- `ui/web_new_v2/js/utils.js` — 760–819, 1275–1314
- `tests/test_api_search.py` — 1–75 (full)
- `.venv_win/Lib/site-packages/webview/util.py` — 228–327 (js_bridge_call threading/serialisation)
- `.venv_win/Lib/site-packages/webview/platforms/edgechromium.py` — 195–234
- `.venv_win/Lib/site-packages/yt_dlp/extractor/soundcloud.py` — search-URL construction

**Callees traced into other areas** (defects in these belong to their owning area, not WN-06):

| Callee | Owning area | Note |
|---|---|---|
| `services/base_service.py::_search_cache` | WN-18 | cache key shapes are built by each provider (WN-19/20/21) |
| `services/track_resolver.py` | WN-18 | alternative "same track" identity |
| `services/catalog_service.py` | WN-24 | album/catalogue resolution, `_catalog_pool` |
| `services/playlist_import_service.py` | WN-24 | provider allow-list is a substring test (see F-4) |
| `services/youtube_service.py` / `soundcloud_service.py` / `spotify_service.py` / `yandex_service.py` | WN-19/20/21 | per-provider search + cache keys |
| `core/database.py` (`add_track`, `get_all_tracks`, `download_queue_add`, `mark_track_downloaded`) | WN-12 | data layer is correct; the *bridge* misuses it (F-1, F-2) |
| `core/downloader.py` (`queue_download`, `_download_worker`) | WN-13 | marks whatever `track_id` it is given (F-1) |
| `core/proxy.py::_safe_stream_local_path` | WN-11 | reviewed — **not** reachable with an attacker-chosen path from WN-06 (see §3) |
| `core/offline.py::available_tracks/offline_library` | WN-03/WN-15 | loads the whole `stream_cache` table per call (folded into F-2) |
| `ui/web_new_v2/js/search.js`, `library.js`, `library-view.js`, `home.js`, `events.js`, `utils.js`, `main.js` | WN-31/WN-32 | consumer side of the contracts in §2/F-1/F-2 |

### 2. Findings

#### F-WN-06-1  [P2] — `download_track` treats the client-supplied `id` as a DB row id; a provider-scoped id skips row creation and orphans the download, and a mismatched (id, source, source_id) repoints an existing library row

- **File:** `core/api.py:2294-2360` (specifically 2299, 2303-2317, 2319-2327, 2347), `core/database.py:2293-2302`, `core/database.py:2330-2359`, `core/database.py:1278-1282`, `core/downloader.py:819`, `services/spotify_service.py:148-161`, `services/spotify_service.py:42-52`
- **Confirmed:** yes
- **Description:** `track_data["id"]` is an overloaded field. For rows coming out of the library it is the `tracks.id` INTEGER; for Spotify search results it is a **provider-scoped string** `"spotify_<trackId>"` (`services/spotify_service.py:150` → `"id": item[0]`, `item[0] = f"spotify_{item.get('trackId', idx)}"`). `download_track` only creates a DB row when `id` is falsy (`if not track_id:` at 2319), so a Spotify search result never gets one. `queue_download` then inserts that string into `download_queue.track_id INTEGER` (`core/database.py:2296`), and after the file lands on disk `mark_track_downloaded` runs `UPDATE tracks SET is_downloaded = 1, file_path = ? WHERE id = ?` (`core/database.py:1278-1282`) with `'spotify_123'` — **no row matches**, so the file is never linked to the library. Symmetrically, when the client *does* supply a numeric DB id together with a `source`/`source_id` pair, the DB row's own stored `source_id` is never consulted: the DB lookup block at `core/api.py:2303-2317` is skipped whenever `source_id` is present (`if not source_id and track_id is not None:`), so the bridge queues a download for `(row_id, source, source_id)` triple that the database never validated, and `mark_track_downloaded` **overwrites `tracks.file_path` of that existing row** with the newly downloaded, unrelated file.
- **Cause:** the bridge contract has no schema for `track_data`. The `id` field's namespace is decided by whichever producer created the object (library row vs provider payload), and the bridge never distinguishes "database row id" from "provider id", nor cross-checks the queued `(source, source_id)` against the row's stored `source_id`.
- **Trigger conditions:** (a) search with `source = "spotify"` (or `source = "all"`, which includes spotify at `core/api.py:2100`), then click the download button on a Spotify result — `ui/web_new_v2/js/utils.js:778-789` passes the raw search object to `download_track`; (b) any payload where `id` is a valid `tracks.id` but `source`/`source_id` name a different item.
- **User impact:** the file is downloaded to `~/.nedotify/downloads` and `download_complete` is emitted (`core/downloader.py:839`), but the track never appears under "Скачанное" / the library, so the user has paid the bandwidth and has an orphaned file with no UI trace. In case (b) an existing library row silently points at a different audio file, and the row's original `file_path` is lost (the column is overwritten, not appended).
- **Evidence:**
  ```python
  # core/api.py:2299-2327
  track_id = track_data.get("id")
  source = track_data.get("source") or "youtube"
  source_id = track_data.get("source_id")

  if not source_id and track_id is not None:      # <-- skipped whenever source_id is present
      ...
  if not track_id:                                # <-- "spotify_123" is truthy -> no row created
      try:
          track_id = self._core.db.add_track(
              title=track_data.get("title", "Unknown"),
              artist=track_data.get("artist", "Unknown Artist"),
              source=source,
              source_id=source_id,
              duration=track_data.get("duration", 0)
          )
  ```
  ```python
  # core/database.py:1278-1282
  def mark_track_downloaded(self, track_id: int, file_path: str) -> None:
      with self._write_lock:
          with self.conn:
              cursor = self.conn.cursor()
              cursor.execute("UPDATE tracks SET is_downloaded = 1, file_path = ? WHERE id = ?", (file_path, track_id))
  ```
  ```python
  # core/database.py:2293-2301  (download_queue DDL)
  CREATE TABLE IF NOT EXISTS download_queue (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      track_id INTEGER NOT NULL,
      ...
  ```
- **Reproduction / verification:** unit level — call `api.download_track({"id": "spotify_123", "source": "spotify", "source_id": "ytsearch1: Artist - Title", "title": "X", "artist": "Y"})` against a scratch DB; assert that `db.get_all_tracks()` is empty afterwards and that `SELECT track_id FROM download_queue` contains the TEXT value `spotify_123`. Cross-check the producer: `services/spotify_service.py:148-161` emits `"id": f"spotify_{trackId}"` and `"source": "spotify"`; `ui/web_new_v2/js/utils.js:782` forwards that object verbatim. For case (b): `api.download_track({"id": <row_id>, "source": "youtube", "source_id": "<different video id>"})` → assert `tracks.file_path` for `<row_id>` changes to the newly downloaded file while the row's stored `source_id` is unchanged.
- **Suggested fix:** split the namespaces in the bridge contract (`track_id` = DB row id, `provider_id` = provider key) and make `download_track` resolve the row by `(source, source_id)` when the id is not a DB row id; before queueing, verify that the row's stored `source_id`/`source` match the pair being queued, and refuse otherwise.
- **Fix side effects:** every producer of `track_data` must be updated (`ui/web_new_v2/js/utils.js:782,1295`, `js/main.js:107`, `js/player.js:2018`, `js/search.js` album/playlist rows). Renaming the field is a breaking bridge change; a backward-compatible shim (`id` kept, `track_id` preferred) avoids a coordinated frontend/backend release.
- **Discovered by:** B

#### F-WN-06-2  [P2] — library / favorites / downloads listings serialise the whole `tracks` table on every mutation event; the bridge exposes no pagination even though the DB layer supports it

- **File:** `core/api.py:2267-2271`, `core/api.py:2273-2275`, `core/api.py:2277-2292`, `core/api.py:2727-2731`, `core/database.py:1184-1209`, `core/database.py:1224-1227`, `core/database.py:1284-1287`, `core/offline.py:62-77`; consumers `ui/web_new_v2/js/events.js:211-231`, `ui/web_new_v2/js/events.js:258-264`, `ui/web_new_v2/js/library.js:321-371`, `ui/web_new_v2/js/library.js:501-546`, `ui/web_new_v2/js/library-view.js:134-150`, `ui/web_new_v2/js/home.js:156-163`
- **Confirmed:** yes
- **Description:** `get_library()` is `self._core.db.get_all_tracks()` with **no limit and no offset**, even though `DatabaseManager.get_all_tracks` accepts `limit`/`offset` (`core/database.py:1186-1188`) and the frontend already has a paginated consumer for smart playlists (`ui/web_new_v2/js/library.js:521-539`). The query is `SELECT * FROM tracks` (`core/database.py:1199-1209`) — every row, every column (~26, including the free-form `metadata_json` blob). The whole list is then handed to pywebview, which serialises it with `json.dumps(result)` **and then two more full string copies** (`.replace('\\','\\\\').replace("'","\\'")`) before embedding it in a JS statement (`webview/util.py:242-243`). The same unbounded pattern applies to `get_favorite_tracks()` (`SELECT * FROM tracks WHERE is_favorite = 1`) and `get_downloaded_tracks()` (`SELECT * FROM tracks WHERE is_downloaded = 1`), and `get_downloaded_tracks` adds one `os.path.exists()` per row (`core/api.py:2290`). On the frontend, **every** `library_updated` / `favorites_updated` / `playlists_updated` / `download_complete` event triggers `loadLibrary()` + `refreshActiveLibraryView()` (`ui/web_new_v2/js/events.js:211-231` and `:258-264`), which between them issue ≈ 6 full-table dumps (get_library ×2, get_favorites ×2, get_downloaded_tracks ×2, plus `get_playlists`), and the downloader emits `library_updated` **and** `download_complete` for every single completed download (`core/downloader.py:835` and `:839`). The `download_complete` branch has **no `isPageVisible('library')` guard** (`ui/web_new_v2/js/events.js:258-264`, unlike the `library_updated` branch at `:223`), so the ≈ 6 full-table dumps happen on every completed download **even when the Library page is not visible**.
- **Cause:** the bridge methods are thin pass-throughs with no paging contract, and the mutation events carry no delta (`library_updated` carries the literal `True`), so the only way the UI can stay correct is to refetch everything.
- **Trigger conditions:** any library mutation — one completed download, one favourite toggle, one playlist edit. A batch download of N tracks produces N such refreshes, and the `download_complete` path is not gated on the Library page being visible.
- **User impact:** the cost of every refresh is O(total library size) in rows serialised, plus O(downloaded rows) filesystem `stat` calls. With a few thousand tracks this is a visible stall on every download completion (even in the background, while the user is on another page) and on every page switch into "Вся музыка"; it grows linearly and unbounded, and the whole payload is materialised in Python, in the bridge string, and in the WebView heap simultaneously.
- **Evidence:**
  ```python
  # core/api.py:2267-2292
  def get_library(self):
      """Get all tracks in local library."""
      if is_offline(self._core.settings):
          return offline_library(self._core.db)
      return self._core.db.get_all_tracks()          # no limit / no offset

  def get_downloaded_tracks(self):
      """Get list of downloaded local tracks (missing files filtered out)."""
      ...
      tracks = self._core.db.get_downloaded_tracks() or []
      result = []
      for t in tracks:
          if not isinstance(t, dict):
              continue
          fp = t.get("file_path")
          if fp and os.path.exists(fp):               # one stat() per row, per call
              result.append(t)
      return result
  ```
  ```python
  # core/database.py:1199-1209
  sql = "SELECT * FROM tracks"
  ...
  if limit:
      sql += " LIMIT ? OFFSET ?"
  cursor.execute(sql, params)
  return [dict(row) for row in cursor.fetchall()]
  ```
  ```js
  // ui/web_new_v2/js/events.js:258-262
  case 'download_complete':
  case 'track_downloaded':
      loadDownloaded();
      loadPlaylists();
      if (window.refreshActiveLibraryView) window.refreshActiveLibraryView();
  ```
- **Reproduction / verification:** instrument `core/database.py::get_all_tracks` (or count `SELECT * FROM tracks` statements) with a scratch DB seeded with 5 000 rows, open the Library page, then complete one download and count the statements between the `download_complete` event and the next render — expect ≥ 5 full scans. Measure wall time of `api.get_library()` and of the bridge round-trip (the pywebview `json.dumps` at `webview/util.py:242` dominates for large libraries). The offline branch is worse: `offline_library` additionally materialises the entire `stream_cache` table (`core/offline.py:63-64`) and does 2 `stat` calls per track.
- **Suggested fix:** add paged bridge methods (`get_library(limit, offset)` / `get_library_count()` using the existing `get_tracks_count`), project only the columns the list view needs instead of `SELECT *`, and turn the mutation events into deltas (or a dirty-flag + count) so the UI does not refetch the whole collection. Move the `os.path.exists` filter into SQL-adjacent data (the `is_downloaded` flag plus a cached existence check) rather than one `stat` per row per call.
- **Fix side effects:** the frontend currently dedups and slices client-side (`ui/web_new_v2/js/library.js:509-517`) and the batch renderer assumes the full array (`makeLibraryBatchRenderer`, `library.js:398-417`); a paged bridge needs a matching renderer. The smart-playlist path (`library.js:521-539`) already implements the paging pattern to copy.
- **Discovered by:** B

#### F-WN-06-3  [P3] — `search` resolves the provider with an unvalidated attribute lookup on `AppCore` (`getattr(self._core, source)`); the bridge can address itself

- **File:** `core/api.py:2098-2106`, `core/api.py:2210-2228`, `core/api.py:346-347`, `core/app.py:107-146`
- **Confirmed:** yes (the lookup is unvalidated and reaches `AppApi` itself); the resulting call currently fails with a `TypeError` that is swallowed.
- **Description:** for any `source` that is not `"all"`, `"local"` or in `DISABLED_UI_PROVIDERS`, the bridge builds `requested_providers = [source]` and then obtains the provider object with `srv = getattr(self._core, name, None)` — an arbitrary attribute name taken straight from the JS payload. `AppCore` exposes roughly 21 public attributes (`db`, `settings`, `session`, `cache`, `scanner`, `resolver`, `engine`, `youtube`, `vk`, `spotify`, `lyrics`, `artists`, `proxy`, `downloader`, `plugins`, `zapret`, `playlist_importer`, `watchdog`, `lufs_scanner`, `audio_fingerprint`, `discord_rpc`) **plus `api`** — the `AppApi` instance itself, installed at `core/api.py:346` (`self._core.api = self`). `AppApi` has a public `search` method with signature `(query, source='all', result_type=None)` (verified: `inspect.signature(AppApi.search)`).
- **Cause:** there is no provider registry — the `AppCore` attribute namespace *is* the dispatch table, so "which providers exist" and "which names may the frontend ask for" are the same, unenforced thing.
- **Trigger conditions:** `window.pywebview.api.search(query, "api")` (or any future attribute whose class exposes a compatible `search`).
- **User impact:** today the call fails with `TypeError: search() got an unexpected keyword argument 'callback'`, which the bridge error-logging wrapper converts into **two `api_error` events pushed to the UI** (`core/api.py:428-441`) plus an empty result set — the user sees an error toast instead of an empty search. The protection against the recursive self-call is an accidental signature mismatch, not a design decision; any future `AppCore` attribute with a `(query, callback=..., error_callback=...)` `search` method would be silently driven by the search fan-out.
- **Evidence:**
  ```python
  # core/api.py:2103-2106
  elif source in DISABLED_UI_PROVIDERS:
      requested_providers = []
  else:
      requested_providers = [source]          # arbitrary string from the bridge
  ```
  ```python
  # core/api.py:2210-2228
  try:
      srv = getattr(self._core, name, None)   # <-- unvalidated attribute lookup
      if not srv or not is_current():
          _finish([])
          return
      if name == "spotify":
          srv.search(query, result_type=result_type, callback=_on_success, error_callback=_on_error, is_current=is_current)
      elif result_type:
          try:
              srv.search(query, result_type=result_type, callback=_on_success, error_callback=_on_error)
          except TypeError:
              srv.search(query, callback=_on_success, error_callback=_on_error)
      else:
          srv.search(query, callback=_on_success, error_callback=_on_error)
  except Exception as exc:
      logger.error("%s search could not start: %s", name, exc)
      _finish([])
  ```
  ```python
  # core/api.py:346-347  (AppApi.__init__)
  self._core = core
  self._core.api = self        # <-- the bridge is an attribute of the object it dispatches into
  ```
- **Reproduction / verification:** `inspect.signature(core.api.AppApi.search)` → `(self, query: str, source: str = 'all', result_type: str = None)`; `hasattr(core.app.AppCore_instance, 'api')` is True once `AppApi.__init__` has run. Drive `api.search("x", source="api")` with the `api` fixture from `tests/conftest.py` and assert that an `api_error` event is emitted and that no provider is contacted.
- **Suggested fix:** replace the `getattr` with an explicit table, e.g. `{"youtube": lambda c: c.youtube, "soundcloud": ..., "spotify": ..., "local": ...}`, and reject unknown sources before any work is scheduled. This also gives the test suite a real fake seam instead of "replace `api._core` with a class that happens to have an attribute named `spotify`" (`tests/test_api_search.py:51-62`).
- **Fix side effects:** the UI currently offers only `all / youtube / soundcloud / spotify / local` (`ui/web_new_v2/js/search.js:152-201`), so an allow-list is a drop-in; `DISABLED_UI_PROVIDERS` (`yandex`, `vk`, `vkontakte`, `zeno`) must stay reachable as an explicit "disabled" verdict rather than silently disappearing.
- **Discovered by:** B

#### F-WN-06-4  [P3] — `import_external_playlist` validates the SSRF target, but the provider allow-list is a substring test and the guard is a one-shot, 120-second-memoised DNS verdict

- **File:** `core/api.py:2362-2367`, `core/api.py:161-195`, `core/api.py:99-130`, `core/api.py:201-220`, `services/playlist_import_service.py:39-58`, `services/playlist_import_service.py:60-136`
- **Confirmed:** the substring allow-list bypass and the one-shot/memoised guard are **confirmed**; the full redirect-to-private-IP chain is a **hypothesis** (needs a live network test).
- **Description:** `import_external_playlist` does the right thing at the bridge level — it extracts the first URL (`_extract_first_url`) and refuses anything that is not an http(s) URL resolving to a public address (`_is_ssrf_safe_url`, `core/api.py:2365`). Local file paths and `file://` URLs are therefore **rejected** (the scheme check at `core/api.py:167-168` only admits `http`/`https`; `_extract_first_url` returns the raw text unchanged when it contains no URL, and that text then fails the scheme check). However: (1) the provider allow-list in the importer is a **substring** test — `if "youtube.com" in target or "youtu.be" in target` / `if "soundcloud.com" in target` (`services/playlist_import_service.py:50-55`) — so `https://attacker.example/youtube.com` is classified as a YouTube playlist and handed to yt-dlp's generic extractor; (2) the guard's DNS verdict is evaluated **once** and memoised per hostname for 120 s (`core/api.py:99`, `124-130`), while the actual fetch is performed later by yt-dlp, which resolves DNS again and follows HTTP redirects; (3) the guard validates only the initial URL, never the redirect chain.
- **Cause:** the allow-list is a text match rather than a parsed-host comparison, and the SSRF decision is decoupled from the socket that actually connects.
- **Trigger conditions:** pasting a URL whose host contains `youtube.com`/`soundcloud.com` as a substring; or a host that answers with a public address at validation time and a private one at fetch time (DNS rebinding) inside the 120 s memo window.
- **User impact:** in this desktop app the blast radius is self-SSRF (the user is the one pasting), so the practical severity is low; but the guard gives a false sense of completeness — it is the app's only defence against a hostile paste and it is bypassable, which matters if the WebView content is ever compromised (the bridge has no authentication of its own, so any script running in the page can call `window.pywebview.api.import_external_playlist`).
- **Evidence:**
  ```python
  # core/api.py:2364-2367
  url = _extract_first_url(url or "")
  if not url or not _is_ssrf_safe_url(url):
      logger.warning("SSRF block triggered for playlist import URL: %s", url)
      return {"success": False, "error": "Некорректная или небезопасная ссылка"}
  ```
  ```python
  # services/playlist_import_service.py:46-58
  if os.path.exists(target) or target.endswith((".m3u", ".m3u8", ".json", ".txt")):
      return self._resolve_local_file(target)
  if "youtube.com" in target or "youtu.be" in target:
      return self._resolve_youtube(target)
  if "soundcloud.com" in target:
      return self._resolve_soundcloud(target)
  raise UnsupportedPlaylistService("Поддерживается импорт плейлистов YouTube, M3U/M3U8, JSON и текстовых списков")
  ```
  ```python
  # core/api.py:99 / 124-130
  _SSRF_CACHE_TTL = 120.0
  ...
  def _ssrf_cache_put(hostname: str, verdict: bool):
      ...
      _ssrf_cache[hostname] = (time.monotonic() + _SSRF_CACHE_TTL, verdict)
  ```
- **Reproduction / verification:** (a) substring bypass — verified statically: `"youtube.com" in "https://attacker.example/youtube.com"` → `True`, so `_is_ssrf_safe_url` passes (the host resolves publicly) and `PlaylistImportService.resolve` takes the YouTube branch; (b) redirect chain — *hypothesis*: needs a local HTTP server that answers `302 Location: http://169.254.169.254/latest/meta-data/` and a host whose DNS flips to a private address inside the 120 s memo window. Evidence still missing: confirmation that yt-dlp's generic extractor follows a cross-host redirect to a link-local address in the installed version (`yt_dlp` in `.venv_win`).
- **Suggested fix:** parse the URL and compare the **host** (or registrable domain) against an explicit allow-list instead of substring matching; re-validate the resolved address at connect time (or hand the already-resolved IP to the fetcher) and repeat the check on every redirect hop.
- **Fix side effects:** the importer must keep accepting SoundCloud short links (`on.soundcloud.com`) and YouTube Music hosts, and `PlaylistImportService.resolve` is also reachable from other callers (WN-24), so the host allow-list belongs there rather than only at the bridge.
- **Discovered by:** B

#### F-WN-06-5  [P3] — one 6-worker pool carries the per-keystroke search fan-out *and* the blocking album-catalogue lookup, so searches can queue behind an 8-second catalogue call

- **File:** `core/api.py:363`, `core/api.py:2161`, `core/api.py:2230`, `core/api.py:2258-2264`, `services/catalog_service.py:14`, `services/catalog_service.py:169`
- **Confirmed:** yes
- **Description:** `_search_executor = ThreadPoolExecutor(max_workers=6, thread_name_prefix="SearchWorker")` (`core/api.py:363`) is used for three different kinds of work: the per-keystroke search fan-out (1 local task + 3 provider tasks per query, `core/api.py:2161` and `:2230`), the album-catalogue lookup (`core/api.py:2264`), and the stream-preview task (`core/api.py:3508`). The album task is the outlier: `CatalogService.album_details` blocks for up to **8 seconds** on a network deadline (`services/catalog_service.py:169`: `deadline = time.monotonic() + 8`), and `CatalogService` already owns a dedicated 4-worker pool (`services/catalog_service.py:14`) that the bridge path does not use. The search's own per-provider budget is only 6 s (`PROVIDER_SEARCH_TIMEOUT = 6.0`, `core/api.py:61`, applied at `:2197`).
- **Cause:** the bridge pool was sized for short fan-out tasks and later reused for a long-blocking call; the fan-out tasks and the blocking tasks have opposite scheduling requirements (fan-out wants breadth, the catalogue call wants a slot held for 8 s).
- **Trigger conditions:** ≥ 6 concurrent `get_album_details` calls (the album modal is opened from a search result and can be opened repeatedly) while the user keeps typing in the search box.
- **User impact:** search fan-out tasks queue behind the album tasks; the results for the *current* query arrive after the 6 s provider budget has already elapsed, so the UI shows the "provider timed out" empty state even though the providers answered — a visible, reproducible "search does nothing" symptom.
- **Evidence:**
  ```python
  # core/api.py:363
  self._search_executor = ThreadPoolExecutor(max_workers=6, thread_name_prefix="SearchWorker")
  ```
  ```python
  # core/api.py:2258-2264
  def run():
      if not current():
          return
      result = self._catalog_service().album_details(album_data if isinstance(album_data, dict) else {}, self._core.db.get_album_tracks, current)
      if current():
          self._emit('album_details_ready', dict(result, request_id=rid))
  self._search_executor.submit(run)
  ```
  ```python
  # services/catalog_service.py:14 / 169
  _catalog_pool = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix='Catalogue')
  ...
  def album_details(self, album, local_lookup=None, is_current=lambda: True, _deadline=None):
      deadline = _deadline if _deadline is not None else time.monotonic() + 8
  ```
- **Reproduction / verification:** start six `get_album_details` calls against a stubbed catalogue that sleeps 8 s (or simply against a slow endpoint), then issue `api.search("x", source="all")` and measure the delay between the call and the `search_results` event — it will exceed `PROVIDER_SEARCH_TIMEOUT` (6 s) while all six workers are busy. Unit-level: monkeypatch `api._search_executor` with a pool of size 1 (as `tests/test_api_search.py:49-50` already does with a fake) and observe the search task queued behind the album task.
- **Suggested fix:** run the album lookup on `CatalogService`'s own `_catalog_pool` (or a dedicated bridge pool) and keep `_search_executor` for short fan-out tasks; alternatively raise the pool size and bound the album task's own deadline to something below the search budget.
- **Fix side effects:** moving the album task off `_search_executor` changes the ordering of `album_details_ready` relative to `search_results` events — the frontend already tolerates out-of-order events (`ui/web_new_v2/js/search.js:610` matches on `request_id`), so the risk is low.
- **Discovered by:** B

### 3. Clean areas

- **Query encoding into provider URLs.** Every provider that builds a URL from the user query encodes it: SoundCloud `urllib_parse.quote(query)` (`services/soundcloud_service.py:320-321`), Spotify/iTunes `urllib.parse.quote(query)` (`services/spotify_service.py:28,60`), and yt-dlp's SoundCloud search builds its URL with `update_url_query(...)` (url-encoded) — verified in the installed `yt_dlp/extractor/soundcloud.py`. The YouTube path goes through `ytmusicapi.search(...)` (`services/youtube_service.py:403`), which parameterises the request. **No query-injection / parameter-smuggling path found.**
- **No provider credential reaches the frontend or the log through the search path.** The `search_results` payload is `{query, source, type, tracks, offline}` (`core/api.py:2111-2117`). The SoundCloud `client_id` is a *public* API id scraped from soundcloud.com (`services/soundcloud_service.py:173-210`), is never logged, and never appears in a track dict. No `yandex_token`, `oauth_client_secret` or proxy credential appears in any WN-06 payload (the bridge masks secrets globally via `_mask_secrets`, `core/api.py:243-253`).
- **SSRF guard is present and blocks local/`file://` targets.** `import_external_playlist` calls `_is_ssrf_safe_url` before fetching (`core/api.py:2365`); the guard rejects non-http(s) schemes (`core/api.py:167-168`), `localhost`/`0.0.0.0`/`::1`, decimal-IP and direct-IP private ranges, and resolves DNS with a bounded, locked, 512-entry memo (`core/api.py:99-158`). `file://` URLs, UNC paths and bare local file paths pasted by the user are all refused (see F-4 for the residual gap).
- **`download_track` cannot write an attacker-chosen `file_path`, `cover_url` or `source_url` into the library.** `add_track` is called with only `title`, `artist`, `source`, `source_id`, `duration` (`core/api.py:2321-2327`) — `file_path`/`cover_url`/`source_url` are never passed, so the `UPDATE tracks SET file_path = ?` branch of `add_track` (`core/database.py:1087-1091`, `1122-1126`) is unreachable from this path. Consequently the "poison the library with an arbitrary path so the proxy serves it" escalation is **not** reachable from WN-06: `core/proxy.py::_safe_stream_local_path` (proxy.py:238-272) only serves a path that is either inside `~/.nedotify/` or referenced by a `tracks` row (`_referenced_by_library`), and the only `file_path` a WN-06 method can cause to be written is the downloader-generated path under `~/.nedotify/downloads` (`core/downloader.py:789`). No `file://`/UNC path reaches the proxy from this area.
- **The search cache is correctly bounded, TTL'd and lock-protected.** `_search_cache` is capped at 300 entries with a 300 s TTL (`services/base_service.py:132-134`), every read/write takes the class-level `_cache_lock` RLock (`base_service.py:251-270`), eviction is true LRU via `_cache_recent` (`base_service.py:223-241`), and a hit does not extend the TTL (`base_service.py:259-262`). Cache keys carry the provider prefix plus the query, the result-type filter and the result limit (`yt_search:{query}:{filter}:{max_results}` at `services/youtube_service.py:382`, `sc_search:{query}:{max_results}` at `soundcloud_service.py:298`, `spotify_search:{query}:{result_type}:{limit}` at `spotify_service.py:111`), so providers cannot collide and a repeated query is served from cache without a network round-trip.
- **The per-provider timeout machinery leaks no threads.** Every `threading.Timer` armed in `_run_provider` is cancelled inside `_finish` (`core/api.py:2175-2187`), including on the error and "provider unavailable" paths; the timer is a daemon.
- **Stale-result suppression is coherent.** `search` uses a generation counter guarded by `_search_lock` (`core/api.py:2090-2096`), `set_offline_mode` bumps the same counter to cancel in-flight searches (`core/api.py:4136-4137`), and `get_album_details` carries an explicit `request_id` that the frontend matches on (`core/api.py:2250-2265` ↔ `ui/web_new_v2/js/search.js:599-618`).
- **Field-name contract between the bridge and the UI matches for the WN-06 methods.** `search_results` → `{query, source, type, tracks, offline}` is consumed exactly as emitted (`ui/web_new_v2/js/search.js:330-383`); `album_details_ready` → `{status, verified, album, tracks, request_id, error?}` matches `fetchAlbumDetails`/`playAlbum` (`ui/web_new_v2/js/search.js:597-647`); `get_library`/`get_favorites`/`get_downloaded_tracks` all return plain arrays of DB rows and the frontend accepts either an array or `{tracks}` (`ui/web_new_v2/js/library.js:504-508`); `get_album_details` returns `{status:'loading', request_id}` and the JS treats any non-`'loading'` status as a terminal answer (`search.js:616`).
- **The search view does not innerHTML provider-controlled strings.** The album and playlist card templates escape every provider field with `escapeHtml` (`ui/web_new_v2/js/search.js:543-558`, `:766-781`), and the track list is built with DOM APIs (`createTrackElement`, `ui/web_new_v2/js/utils.js:688`). No XSS → bridge escalation was found on the WN-06 path.

### 4. Coverage gaps

- **The full DNS-rebinding / redirect-to-private-IP chain in F-4 was not executed.** It needs a live HTTP server and a rebinding DNS server; I verified the two static halves (substring allow-list, one-shot memoised verdict) but did not run the network proof. The missing evidence is a recorded yt-dlp extraction that follows a cross-host 302 to a link-local address.
- **No live provider traffic.** All provider behaviour was read from source (`services/youtube_service.py`, `soundcloud_service.py`, `spotify_service.py`) and from the installed `yt_dlp`; the `network`-marked tests were not run, so provider-specific runtime behaviour (rate limits, yt-dlp extractor changes) is unverified.
- **`core/proxy.py` was only read at the `_safe_stream_local_path` level** (proxy.py:23-24, 238-303). The full proxy request path (WN-11) was not audited, so I can state only that the WN-06 methods cannot *write* an arbitrary `file_path`; I did not verify the proxy's own handling of a `file_path` that arrives from a non-WN-06 writer.
- **The `tracks` table row count on a real user profile was not measured** — F-2's severity is therefore argued from the code path (unbounded `SELECT *`, full-list serialisation, 6 dumps per event), not from a profiled 5 000-row library. `~/.nedotify/` was deliberately not touched.
- **`core/api.py` was read at the physical line numbers given in the brief.** I did not re-derive them from the current file head, so if the file changed after the brief was written, the quoted ranges may drift by a few lines.
- **The `search` fan-out was not exercised under load** — F-5's delay figure is derived from the pool sizes and deadlines in source, not from a measured reproduction.
- **`services/track_resolver.py`, `services/music_matching.py` and `services/artist_identity.py` were read for context only**; their own matching behaviour belongs to WN-18 and was not evaluated.

### 5. Architecture improvements (ARCH)

These are improvements **without a proven defect**; they are reported separately and must not be mixed into the defect list above.

1. **`search` is a monolith with five responsibilities in one method** (`core/api.py:2077-2232`): provider selection policy, offline redirection, staleness generation, per-provider timeout scheduling, event emission and completion tracking. Extract a `SearchCoordinator` that owns provider fan-out + deadlines and returns typed per-provider results; the bridge method should only translate them into events. `CatalogService._cached/_flights` (`services/catalog_service.py:44-70`) and `BaseMusicService._join_request` (`services/base_service.py:140-161`) are already good models for this shape in this codebase.
2. **The backend never merges provider results — the frontend does** (`core/api.py:2108-2117` emits one chunk per provider; `ui/web_new_v2/js/search.js:366-377` merges). Consequence: the backend cannot cap the total number of rows shipped to the WebView (4 providers × 20 rows, each with a cover URL, per keystroke-debounced query), cannot rank, and cannot collapse the same song found on two providers. The same "which rows does the UI hold" question is then answered in four different places with four different keys: `trackDedupKey` in `js/search.js:320-328` (source+source_id), the library key in `js/library.js:511` (`id || source_id || title__artist`), `TrackResolver._memo_key` (`services/track_resolver.py:117-119`, normalised title+artist) and `CatalogService`'s similarity matching (`services/catalog_service.py:201,236`). One canonical identity helper — `services/music_matching.py` already exists for this — used by both sides would fix the duplication and the search duplicates at once.
3. **There are two unrelated request-staleness mechanisms.** `search` uses an opaque generation counter that is *not* carried in the payload (the frontend re-derives staleness from the query string, `js/search.js:332,351`), while `get_album_details`, `get_artist_profile` and `get_track_wave` carry an explicit `request_id`. `set_offline_mode` additionally reuses the *search* generation counter to cancel in-flight searches (`core/api.py:4136`). A single `RequestContext` (id + generation + deadline) emitted with every async payload would remove the ad-hoc coupling.
4. **`AppApi` carries 136 public bridge methods** (measured: `len([n for n,_ in inspect.getmembers(AppApi, inspect.isfunction) if not n.startswith('_')]) == 136`) with a single flat namespace, all wrapped by one error-logging decorator. A per-domain façade (`SearchFacade`, `LibraryFacade`, `CatalogFacade`) behind the same bridge names would keep the public surface stable while letting the internals split — this area's `search` alone spans policy, scheduling and transport.
5. **The provider dispatch should be an explicit table, not an attribute lookup** (see F-3). Beyond fixing the hazard, it would give the test suite a first-class fake seam; today `tests/test_api_search.py:51-62` has to fabricate a `Core` class whose attribute names happen to match the dispatch keys, which is precisely why the dispatch cannot be tightened without breaking tests.
6. **The search cache key is built independently by each provider** (`yt_search:`, `sc_search:`, `spotify_search:`, `ya_search:`) with different field sets — the Yandex key omits `max_results` (`services/yandex_service.py:115`), the others include it. A shared key builder on `BaseMusicService` (e.g. `search_cache_key(provider, query, kind, limit)`) would make the keys auditable in one place; the Yandex omission itself is WN-21's defect.
7. **`_catalog_service()` lazily constructs a service under the *window operations* lock** (`core/api.py:2236`, `self._window_op_lock` — the same RLock used for mini-player, resize and snap geometry at `core/api.py:731, 1211, 1269, 1298, 3466, 3481`). A service-lifecycle lock mixed with a UI lock means a window operation and a catalogue initialisation contend for the same mutex. The codebase rule in `AGENTS.md` is that a new shared field joins *its own class's* existing lock; a lazily-created `CatalogService` deserves its own.
8. **`search` logs the raw user query at INFO on every debounced search** (`core/api.py:2083`: `logger.info(f"api.py -> search called: query='{query}', ...")`) into `~/.nedotify/logs/app.log`, unredacted and unescaped (a query containing newlines can forge log lines). Logging the query length or a hash would keep the diagnostics without copying whatever the user typed into a persistent file.
9. **Dead and duplicated public surface in this area.** `get_favorites()` is a pure alias of `get_favorite_tracks()` (`core/api.py:2273-2275`), and `get_album_tracks()` (`core/api.py:2244-2248`) is called by **no** frontend code in `ui/web_new_v2/` (only by `tests/test_api_search`-adjacent tests) yet still performs a synchronous catalogue round-trip with an 8 s budget on the bridge thread. Retiring the alias and the dead method would shrink the surface that `AppApi` has to keep working.
10. **The listing events carry no delta.** `library_updated` is emitted with the literal `True` (`core/downloader.py:835`) and `favorites_updated` carries the *entire* favourite list as its payload (`core/api.py:2627, 2724`), so a single favourite toggle ships the whole collection to the UI. Emitting `{track_id, is_favorite}` and letting the UI patch its model would remove the largest single source of the F-2 refetch storm.
