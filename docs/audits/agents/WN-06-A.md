## AREA WN-06 — Bridge search, catalog, library listing, favorites, downloads listing — ROLE A

### 1. Scope reviewed

**Files opened (path: line ranges actually read)**

- `core/api.py` L150-229 (`_is_ssrf_safe_url`, `_extract_first_url`), L232-341 (helpers), L340-499 (`AppApi.__init__`, `_install_bridge_error_logging`, `_offline_bridge_result`), L1112-1166 (`_emit`), **L2077-2389 (`search`, `_catalog_service`, `get_album_tracks`, `get_album_details`, `get_library`, `get_favorites`, `get_downloaded_tracks`, `download_track`, head of `import_external_playlist`)**, L2546-2674 (`get_playlist_tracks`, `toggle_favorite` — cross-check only), **L2700-2759 (`get_favorite_tracks`)**, L4125-4164 (`set_offline_mode` — cross-check).
- `services/base_service.py` L1-329 (`_SharedExecutor`, `BaseMusicService`, `_join_request`, search cache).
- `services/catalog_service.py` L1-251 (`CatalogService.album_details`, `_cached`, `_call`).
- `services/spotify_service.py` L20-244 (`_cached_spotify_search`, `_cached_spotify_album_search`, `SpotifyService.search`, `get_playlist_tracks`).
- `services/youtube_service.py` L360-529 (`YouTubeService.search`), L600-774 (`get_album_tracks`, playlist tracks).
- `services/soundcloud_service.py` L290-370 (`SoundCloudService.search`).
- `services/artist_service.py` L250-279 (track `id` shape — cross-check).
- `core/database.py` L175-234 (thread-local connection), L1054-1164 (`add_track`), L1166-1300 (`get_track`, `get_all_tracks`, `get_favorite_tracks`, `get_downloaded_tracks`), L1349-1509 (`_like_pattern`, `search_tracks`, `search_albums`, `search_playlists`, `get_album_tracks`), L2284-2423 (`ensure_download_queue_table`, `download_queue_add`).
- `core/downloader.py` L40-320 (`DownloadManager`, `_decrement_batch_total_for_dedup`), L350-500 (`queue_download`), L600-889 (`_fetch_from_provider`, `_fetch_with_retry`, `_download_worker`, `_execute_download_worker`).
- `core/offline.py` L1-77 (`is_offline`, `available_tracks`, `offline_library`).
- `core/app.py` L115-214 (provider wiring; `soundcloud` is a **lazy property**).
- `ui/web_new_v2/js/search.js` L1-1125 (`onSearchResults`, `renderResults`, `fetchAlbumDetails`, `openAlbumModal`, `runSearchQuery`).
- `ui/web_new_v2/js/events.js` L70-320 (`search_results` / `search_completed` / `album_details_ready` / `download_complete` / `download_failed` routing).
- `ui/web_new_v2/js/utils.js` L1-70 (`filterVisibleTracks`), L688-827 (`createTrackElement`), L963-1054 (`matchDownloadTarget`, `clearDownloadSpinner`).
- `ui/web_new_v2/js/library.js` L300-549, `ui/web_new_v2/js/library-view.js` L125-164, `ui/web_new_v2/js/artist_profile.js` L180-224, `ui/web_new_v2/js/main.js` L85-144.
- `tests/test_api_search.py` (L1-75), `tests/test_catalog_verification.py` (L130-169), `tests/conftest.py` (L1-130) — used to establish the intended contract.

**Callees traced into other areas**

| Callee | Owner area | Note |
|---|---|---|
| `core/downloader.py::queue_download` / `_download_worker` / `download_queue_add` | WN-13 / WN-12 | traced; two defects are attributed here (the `track_id` contract and the missing event) |
| `core/database.py::mark_track_downloaded`, `add_track`, `download_queue_add` | WN-12 | traced; the string-id break is caused by the *caller* (WN-06) |
| `services/catalog_service.py::album_details` | WN-24 | traced; the synthetic `id` it stamps on album tracks is the input that breaks `download_track` |
| `services/spotify_service.py::search` | WN-21 | traced; ignores `result_type='playlists'` |
| `services/youtube_service.py`, `services/soundcloud_service.py` | WN-19 / WN-20 | traced for result shape |
| `services/base_service.py::_join_request` / `_SharedExecutor` | WN-18 | traced; no WN-06-owned defect found there |
| `ui/web_new_v2/js/search.js`, `library.js`, `utils.js`, `events.js` | WN-31 / WN-32 / WN-28 | traced for the field-name contract and the spinner behaviour |
| `services/track_resolver.py` | WN-18 | **not on the WN-06 call path** — it is reached only from `core/downloader.py:515` and `services/recommendation_service.py:56` |
| `core/app.py::soundcloud` (lazy property) | WN-02 | traced; provider instantiation is correctly off the bridge thread |

**Reproduction harnesses written (outside the repo):**
`%TEMP%\opencode\repro_wn06.py`, `%TEMP%\opencode\repro_wn06_b.py` — hermetic (temp SQLite, stub providers, no network, no real `~/.nedotify`).

---

### 2. Findings

#### F-WN-06-1  [P1] — `download_track` treats a provider's synthetic string id as a DB row id: album / artist tracks download successfully but never enter the library

- **File:** `core/api.py:2299-2335` (root cause), `core/api.py:2346-2347` (the bad call), `services/catalog_service.py:244` and `services/catalog_service.py:208` (the id shape that triggers it), `services/artist_service.py:263` (second trigger), `core/downloader.py:819` (where the link is silently lost).
- **Confirmed:** yes
- **Description:** `download_track` takes `track_data["id"]` as the library row id. Search results from the YouTube/SoundCloud track search have **no** `id` key, so the bridge inserts a row via `add_track` and everything works. But album results from `CatalogService.album_details` and artist-profile tracks carry a **synthetic string id** (`"yt_<videoId>"` / `"spotify_<trackId>"`). That string is truthy, so the `if not track_id:` branch that persists the track is skipped, and the string is handed straight to `queue_download` as if it were an `INTEGER PRIMARY KEY`.
- **Cause:** `track_id` is never validated to be an integer DB row id. `if not source_id and track_id is not None:` (L2303) is skipped because `source_id` *is* present, so the "look up the real row" repair path never runs; `if not track_id:` (L2319) is skipped because the string is truthy.
- **Trigger conditions:** open an album from the search results (YouTube Music album or iTunes/Spotify album) or an artist profile, click the download button on a track in the album modal, and let the download finish.
- **User impact:** the MP3 is written into `~/.nedotify/downloads/` and the queue row is marked `completed`, but **no row is ever created in `tracks`** — `mark_track_downloaded` executes `UPDATE tracks SET is_downloaded=1, file_path=? WHERE id='yt_abc123'`, which matches 0 rows. The track never appears in “Офлайн”, never gets `is_downloaded=1`, and the file is an orphan on disk. The UI nevertheless paints the row’s button as “Скачан” (the `download_complete` event matches the row by `id`), so the user believes the download succeeded while nothing is playable. The queue row also stores a TEXT value in the `track_id` INTEGER column, which breaks the per-track uniqueness/dedup contract of `download_queue`.
- **Evidence:**
  ```python
  # core/api.py:2299-2327
  track_id = track_data.get("id")          # "yt_abc123"  (string!)
  source = track_data.get("source") or "youtube"
  source_id = track_data.get("source_id")  # "abc123"
  if not source_id and track_id is not None:
      ...                                     # skipped: source_id is present
  if not track_id:                           # skipped: the string is truthy
      track_id = self._core.db.add_track(...)
  ```
  ```python
  # services/catalog_service.py:244 (the album track the user clicks)
  tracks.append({'id': 'yt_' + video, 'source': 'youtube', 'source_id': video, ...})
  ```
  ```python
  # core/downloader.py:819
  self._core.db.mark_track_downloaded(track_id, file_path)   # UPDATE ... WHERE id = 'yt_abc123' -> 0 rows
  ```
- **Reproduction / verification:** `%TEMP%\opencode\repro_wn06.py` builds the exact dict `services/catalog_service.py:244` produces and calls `api.download_track(...)`:
  ```
  download_track returned: True
  download_queue rows: [{'track_id': 'yt_abc123', 'source': 'youtube', 'source_id': 'abc123', 'status': 'pending', ...}]
  tracks rows after download_track: []
  in-memory queue item: {'track_id': 'yt_abc123', 'source': 'youtube', 'source_id': 'abc123', ...}
  tracks rows after worker: []                <-- the download finished, the library is still empty
  download_queue after worker: [{'track_id': 'yt_abc123', 'status': 'completed'}]
  download_complete events: [... ('download_complete', {'track_id': 'yt_abc123'})]
  ```
  The control case (a plain search dict with no `id`) behaves correctly: `tracks rows: [{'id': 1, 'title': 'Plain', 'source_id': 'zzz999', ...}]`.
- **Suggested fix:** in `download_track`, treat `track_data["id"]` as a DB row id only when it is an `int` (or a digit string); otherwise resolve the row via `db.get_track_by_source_id(source, source_id)` and, if there is still none, insert it with `add_track(...)` before queueing. Never let a non-integer id reach `queue_download`.
- **Fix side effects:** `add_track` already de-duplicates on `(source, source_id)` (`core/database.py:1077-1092`), so the insert path is idempotent. The `download_queue` rows already written with TEXT ids would need a one-off migration/cleanup, otherwise a re-download of the same album track will keep hitting the “already completed” row.
- **Discovered by:** A

---

#### F-WN-06-2  [P2] — `download_track` returns `False` with **no event** when the queue rejects or de-duplicates the request, so the caller’s download spinner never clears

- **File:** `core/api.py:2356-2359`, `core/downloader.py:374-376` and `core/downloader.py:402-406` (the two rejection paths), `ui/web_new_v2/js/utils.js:767-791` (the spinner), `ui/web_new_v2/js/events.js:266-281` (the only reset path).
- **Confirmed:** yes
- **Description:** `download_track` returns a bare `False` when `queue_download` refuses the item (already queued, already in the `download_queue` table, or an in-memory duplicate). It emits **no** `download_failed` and **no** `download_queue_updated` on that path. The frontend sets `download-btn.downloading` + a spinner before the call and only clears it from the `download_failed` event (`events.js:269-274`) or from the `nedotify:track_downloaded` handler (`utils.js:1008-1017`). A `False` return resolves the promise normally, so the `catch` in `utils.js:783` never runs and no event ever arrives.
- **Cause:** the bridge treats “queued” and “rejected” as the same value in a boolean return, and only the *failure* branches emit `download_failed`. There is no event for the “nothing to do” outcome.
- **Trigger conditions:** click download on a track whose `download_queue` row already exists (`pending`/`downloading`/`completed`) — e.g. the same track from two views, or an album track after F-WN-06-1 has already “completed” it. Also reachable via the “Скачать все” button over an already-downloaded selection.
- **User impact:** the row’s download button spins forever; the user is never told that the track was already queued. The library never changes, so the user retries repeatedly.
- **Evidence:**
  ```python
  # core/api.py:2356-2359
  if not queued:
      # Duplicate or rejected by the queue manager. queue_download has
      # already shrunk the batch denominator for this case.
      return False
  ```
  ```python
  # core/downloader.py:374-376
  if not added:
      self._decrement_batch_total_for_dedup()
      return False
  ```
  ```javascript
  // ui/web_new_v2/js/utils.js:773-789  — the spinner is added, and only the
  // rejected-promise branch removes it.
  downloadBtn.classList.add('downloading');
  ...
  await window.pywebview.api.download_track(track);   // resolves with false -> no reset
  } catch(err) { ...reset... }
  ```
- **Reproduction / verification:** call `api.download_track(<track already in download_queue>)` — the promise resolves with `false` and `api._emit` records **no** `download_failed` event (the `emitted` list stays empty). Equivalent UI repro: download an album track twice; the second click leaves the spinner running.
- **Suggested fix:** distinguish the outcomes — e.g. return `{"queued": bool, "reason": "duplicate"|"queued"}`, or emit a `download_queue_updated`/`download_skipped` event carrying the `source_id` on the rejection path so the UI can clear the spinner.
- **Fix side effects:** the UI currently treats any `download_failed` as an error toast; a new “skipped” event must not raise an error toast, or the user will see a spurious failure message on every double click.
- **Discovered by:** A

---

#### F-WN-06-3  [P2] — `download_complete` carries only the DB row id, so a search row (which is keyed by `source_id`) never clears its spinner, even on a successful download

- **File:** `core/api.py:2294-2360` (the bridge never publishes a `source_id`-keyed signal), `core/downloader.py:839` (the event payload), `ui/web_new_v2/js/utils.js:977-991` (`matchDownloadTarget`), `ui/web_new_v2/js/utils.js:1008-1017` (the reset handler).
- **Confirmed:** yes (code-path analysis; no UI run)
- **Description:** the bridge resolves a provider result to a DB row id before queueing (`add_track` → `track_id`), and the worker then emits `download_complete {"track_id": <int row id>}`. The search view, however, identifies a row by `source_id`: `createTrackElement` sets `item.dataset.trackSourceId = String(track.source_id || track.id || '')`, and `matchDownloadTarget` compares that dataset value against `data.track_id` (and `data.source_id`, which `download_complete` does not carry).
- **Cause:** the two sides use different identities for the same track — the DB row id on the Python side, the provider id on the JS side — and the event carries only the former.
- **Trigger conditions:** download any track from the **search results** (YouTube, SoundCloud or Spotify). The provider `source_id` (e.g. `dQw4w9WgXcQ`) never equals the integer DB row id, so `matchDownloadTarget` returns `false` and `clearDownloadSpinner` is never called.
- **User impact:** the download button of the clicked row keeps spinning indefinitely, even though the download succeeded. The library view recovers (it is re-rendered from scratch), the search view does not.
- **Evidence:**
  ```python
  # core/downloader.py:839
  self._emit('download_complete', {'track_id': track_id})   # int DB row id, no source_id
  ```
  ```javascript
  // ui/web_new_v2/js/utils.js:981-990
  const tid = (data.track_id !== undefined && data.track_id !== null) ? String(data.track_id) : '';
  const sid = (data.source_id !== undefined && data.source_id !== null) ? String(data.source_id) : '';
  const ds  = el.dataset && el.dataset.trackSourceId ? String(el.dataset.trackSourceId) : '';
  if (ds && ((tid && ds === tid) || (sid && ds === sid))) return true;
  ```
- **Reproduction / verification:** in the search view, click the download button on any YouTube result and wait for `download_complete` in the console log — `data.track_id` is an integer while `el.dataset.trackSourceId` is the video id, so `matchDownloadTarget` is false and the button keeps the `downloading` class.
- **Suggested fix:** include the provider identity in the completion/failure events (`{"track_id": ..., "source_id": ..., "source": ...}`) so the DOM matcher can correlate rows; `WIN_AUDIT_CONTEXT.md` rule 7 only forbids `file_path` in `download_complete`, not `source_id`.
- **Fix side effects:** the event payload shape is owned by WN-13 (`core/downloader.py`) and consumed by WN-32 (`utils.js`); adding a field is backward compatible, but every `download_complete`/`download_failed` emitter must be updated consistently (the downloader, `AppApi.download_track`, and the batch paths).
- **Discovered by:** A (root cause in the WN-06 bridge contract; event payload owned by WN-13, DOM matching by WN-32)

---

#### F-WN-06-4  [P2] — Search results are not normalised across providers: the Spotify provider ignores `result_type='playlists'` and returns tracks, which the UI renders as playlist cards

- **File:** `core/api.py:2217-2225` (the bridge forwards `result_type` verbatim and does not normalise), `services/spotify_service.py:110-166` (the provider only understands `albums`), `ui/web_new_v2/js/search.js:406-433` (the UI turns any non-playlist item into a playlist card).
- **Confirmed:** yes
- **Description:** `search` passes `result_type` to every provider and merges the answers into one list without normalising them. `SpotifyService.search` only branches on `result_type in ('albums','album')`; for `'playlists'` it falls into the **track** branch and returns ordinary tracks (no `type` field). The UI, in the “Плейлисты” filter, converts any item without `type === 'playlist'` into a synthetic playlist card.
- **Cause:** no shared result contract between `AppApi.search` and the providers; each provider decides for itself what `result_type` means, and the bridge does not check what came back.
- **Trigger conditions:** select the “Плейлисты” sub-filter with the “Все площадки” or “Spotify” source and any non-empty query.
- **User impact:** Spotify **tracks** are displayed as playlist cards. Clicking one calls `get_playlist_tracks(<track id>, 'spotify')`, which does an iTunes *track* lookup and yields nothing — the modal reports “Треки этого плейлиста недоступны”. The user is actively misinformed about what the result is.
- **Evidence:**
  ```python
  # services/spotify_service.py:124-147
  is_album_search = result_type in ("albums", "album")
  if is_album_search:
      ...
  else:
      raw_tuple = _cached_spotify_search(query, limit, is_current)   # <- 'playlists' lands here
      tracks = [{"id": item[0], "title": item[1], ...}]                # no "type" key
  ```
  ```javascript
  // ui/web_new_v2/js/search.js:406-426
  if (currentType === 'playlists') {
      tracks.forEach((t, idx) => {
          if (t.type === 'playlist') { ... }
          else { playlistMap.set(key, { id: t.id || `playlist_${idx}`, title: t.title || 'Плейлист',
                                         author: t.artist || t.author || 'NeDotify', type: 'playlist', ... }); }
  ```
- **Reproduction / verification:** switch the search filter to “Плейлисты”, keep the source on “Все площадки”, search for any popular song title. The Spotify chunk of `search_results` contains plain tracks (no `type`), and the UI renders them as “Плейлист” cards.
- **Suggested fix:** either implement the playlist search in the Spotify provider (owner: **WN-21**) or have `AppApi.search` drop/flag provider chunks whose `type` does not match the requested `result_type` before emitting them (owner: **WN-06**).
- **Fix side effects:** dropping non-matching chunks would also silence the SoundCloud track results that currently leak into an “albums” search (the SoundCloud provider has no `result_type` parameter at all, so `core/api.py:2219-2223` silently falls back to a plain track search).
- **Discovered by:** A

---

#### F-WN-06-5  [P2] — `get_library` / `get_favorites` / `get_downloaded_tracks` expose no pagination: the whole table is always materialised and pushed across the bridge

- **File:** `core/api.py:2267-2292`, `core/api.py:2727-2731`, `core/database.py:1184-1209` (`get_all_tracks` — supports `limit`/`offset`/`order_by`), `core/database.py:1224-1227`, `core/database.py:1284-1287`.
- **Confirmed:** yes
- **Description:** the database layer already supports `limit`/`offset`/`order_by` for `get_all_tracks`, but the bridge methods expose **no** pagination parameters at all. `get_library()` calls `get_all_tracks()` with `limit=None`, which drops the `LIMIT` clause entirely; `get_favorite_tracks()` and `get_downloaded_tracks()` run unbounded `SELECT *` queries. `get_downloaded_tracks()` additionally performs one `os.path.exists()` per row, synchronously, on the bridge thread.
- **Cause:** the bridge surface was never given a pagination contract, so the caller cannot ask for a page and the backend cannot push one.
- **Trigger conditions:** any user whose library has grown to thousands of tracks opens the Library page (`loadLibraryOverview` → `get_library()`), opens an artist profile (`artist_profile.js:192` fetches the **entire** library only to filter it by artist), or opens “Любимые”/“Офлайн”.
- **User impact:** a multi-megabyte JSON payload is built and transferred synchronously on every library/artist-profile open, freezing the bridge thread for the duration; memory grows with the library; there is no way for the UI to page.
- **Evidence:**
  ```python
  # core/api.py:2267-2271
  def get_library(self):
      """Get all tracks in local library."""
      if is_offline(self._core.settings):
          return offline_library(self._core.db)
      return self._core.db.get_all_tracks()          # no limit -> no LIMIT clause
  ```
  ```python
  # core/database.py:1205-1207
  if limit:
      sql += " LIMIT ? OFFSET ?"
  ```
  ```python
  # core/database.py:1226 / 1286
  cursor.execute("SELECT * FROM tracks WHERE is_favorite = 1 ORDER BY added_at DESC")
  cursor.execute("SELECT * FROM tracks WHERE is_downloaded = 1 ORDER BY added_at DESC")
  ```
- **Reproduction / verification:** `%TEMP%\opencode\repro_wn06_b.py` inserts three tracks and prints `get_library() -> 3 rows (unbounded)`. The SQL trace (`SELECT * FROM tracks` with no `LIMIT`) confirms the behaviour for any table size.
- **Suggested fix:** add `limit`/`offset` parameters to the bridge methods (defaulting to a sane page size), and let `library.js` request pages — the JS already renders in batches of 50 (`library.js:395 LIB_BATCH_SIZE`) and would benefit from a real page contract.
- **Fix side effects:** the UI currently relies on `get_library()` returning the complete set (`library-view.js:143` prints `libraryTracks.length` as the collection count and `artist_profile.js:194` filters the whole list). Any pagination change must keep a separate count endpoint or the “N треков в коллекции” label will start showing the page size.
- **Discovered by:** A

---

#### F-WN-06-6  [P3] — `search` emits no `search_completed` for an empty/whitespace-only query, breaking the documented “results arrive via events” contract

- **File:** `core/api.py:2084-2088` (the short-circuit), `core/api.py:2078-2081` (the docstring that promises the completion event), `tests/test_api_search.py:31-33` (the behaviour is currently pinned by a test).
- **Confirmed:** yes
- **Description:** the docstring says “Results arrive via the `search_results` / `search_completed` events”, but for an empty query the method returns `{"query": "", "tracks": []}` **before** any provider is scheduled and **without** emitting `search_completed`. A caller that waits for the completion event waits forever. The same applies to the return value in the normal case: the bridge always returns `"tracks": []` and the real results only ever arrive by event.
- **Cause:** the empty-query guard returns before the completion machinery is set up.
- **Trigger conditions:** any caller that forwards an empty/whitespace query to `api.search(...)`. The shipped UI happens to pre-validate (`search.js:78`, `search.js:105`, `search.js:844`), so today the bug is latent — but the *contract* is broken and the current test pins the broken behaviour rather than the contract.
- **User impact:** a permanent “Поиск…” spinner if any future/other caller passes an empty query.
- **Evidence:**
  ```python
  # core/api.py:2084-2088
  query = (query or "").strip()
  if is_offline(getattr(self._core, 'settings', None)):
      source = 'local'
  if not query:
      return {"query": "", "tracks": []}          # <- no search_completed
  ```
  ```python
  # tests/test_api_search.py:31-33
  def test_empty_query_short_circuits(api, emitted):
      assert api.search("   ", source="yandex") == {"query": "", "tracks": []}
      assert emitted == []
  ```
- **Reproduction / verification:** `%TEMP%\opencode\repro_wn06_b.py`: `search('') -> {'query': '', 'tracks': []}` and `events after empty query: []` — no `search_completed`.
- **Suggested fix:** emit `search_completed` (with an empty result set) before returning on the empty-query path, and update `tests/test_api_search.py:31-33` accordingly.
- **Fix side effects:** the existing test asserts `emitted == []`; it will need to be changed. The JS `onSearchResults` handles an empty completion chunk (`search.js:334-346`), so no UI change is needed.
- **Discovered by:** A

---

#### F-WN-06-7  [P3] — `search` applies no length limit to the query and no normalisation to the `source` argument

- **File:** `core/api.py:2084`, `core/api.py:2098-2106`, `core/database.py:1366-1404` (FTS5 term construction).
- **Confirmed:** yes
- **Description:** (a) The query is passed to the providers and to `db.search_tracks` with no upper bound. `search_tracks` builds one quoted prefix term **per whitespace-separated word** (`'"' + w.replace('"','""') + '"*'`), so a 100 kB paste produces a 100 kB FTS5 `MATCH` expression; the FTS error is swallowed (`database.py:1390-1391`) and the LIKE fallback runs, which is a full table scan. (b) `source` is matched case-sensitively against `"all"` / `"local"` and against the `DISABLED_UI_PROVIDERS` set, and is otherwise used **verbatim as an attribute name** on the core object (`getattr(self._core, name, None)`). `"YouTube"` therefore silently yields an empty search, and an arbitrary string is used for an attribute lookup on `AppCore`.
- **Cause:** no normalisation/validation of the two caller-supplied arguments.
- **Trigger conditions:** (a) pasting a very long string into the search box; (b) any caller that passes a differently-cased source name.
- **User impact:** (a) a long paste degrades into a full-table LIKE scan and a multi-megabyte request to every provider; (b) a mis-cased source silently returns “ничего не найдено”.
- **Evidence:**
  ```python
  # core/api.py:2098-2106
  DISABLED_UI_PROVIDERS = {"yandex", "vk", "vkontakte", "zeno"}
  if source == "all":       requested_providers = ["local", "youtube", "soundcloud", "spotify"]
  elif source == "local":   requested_providers = ["local"]
  elif source in DISABLED_UI_PROVIDERS: requested_providers = []
  else:                     requested_providers = [source]
  ```
  ```python
  # core/api.py:2213
  srv = getattr(self._core, name, None)     # `name` is the caller-supplied source
  ```
- **Reproduction / verification:** code path only; `api.search("q", source="YouTube")` produces `requested_providers == ["YouTube"]` → `getattr(core, "YouTube", None) is None` → `_finish([])` → an empty, “completed” search.
- **Suggested fix:** `source = str(source or "all").strip().lower()` and restrict the accepted set to the providers that are actually wired; cap the query length (e.g. 256 chars) before dispatch.
- **Fix side effects:** a hard provider allow-list would break the lazy `AppCore.soundcloud`/`yandex` properties if a future provider is added without updating the list; the allow-list belongs next to the provider wiring in `core/app.py`.
- **Discovered by:** A

---

#### F-WN-06-8  [P3] — `search_completed` is emitted while `pending_lock` is held, contrary to the project’s own “`_emit` must not run under our locks” rule

- **File:** `core/api.py:2123-2129`, compare `core/downloader.py:208-211` (the rule stated in the codebase).
- **Confirmed:** yes
- **Description:** `mark_done` acquires `pending_lock` and calls `self._emit("search_completed", ...)` inside the `with` block. `AppApi._emit` on a non-main thread calls `self._window.evaluate_js(js_code)` **synchronously** (`core/api.py:1156-1159`), which pywebview marshals through `Control.Invoke` — i.e. the provider callback thread blocks until the WebView has executed the JS, while holding `pending_lock`.
- **Cause:** the completion event is emitted from inside the critical section instead of after it.
- **Trigger conditions:** the last provider of a search finishing.
- **User impact:** none observed today (no other code path takes `pending_lock`, so there is no deadlock), but the pattern is the exact one the project documents as forbidden and it makes the provider callback thread hostage to WebView responsiveness.
- **Evidence:**
  ```python
  # core/api.py:2123-2129
  def mark_done(provider_name):
      with pending_lock:
          pending_providers.discard(provider_name)
          if not pending_providers and not completion_emitted[0]:
              completion_emitted[0] = True
              if is_current():
                  self._emit("search_completed", {"query": query, "source": source})   # <- under the lock
  ```
  ```python
  # core/downloader.py:208-211 — the project's own rule
  # Emit outside both _lock and (when called from queue_download) _queue_lock:
  # _emit crosses the pywebview bridge and must not run under our locks.
  ```
- **Reproduction / verification:** static; the `_emit` call site is textually inside the `with pending_lock:` block.
- **Suggested fix:** compute the payload under the lock and emit after leaving the `with` block (same shape as `_decrement_batch_total_for_dedup`).
- **Fix side effects:** none — `completion_emitted` already guarantees a single emission.
- **Discovered by:** A

---

#### F-WN-06-9  [P3] — `get_album_tracks` (bridge) runs the whole catalogue lookup synchronously on the bridge thread, with an 8 s budget and no request-id guard

- **File:** `core/api.py:2244-2248`, `services/catalog_service.py:168-189`, `services/catalog_service.py:34-42` (`_call`).
- **Confirmed:** yes
- **Description:** unlike `get_album_details` (which hands the work to `_search_executor` and emits an event with a `request_id`), `get_album_tracks` runs `CatalogService.album_details(...)` inline on the calling thread. For a local album that includes a YouTube Music verification search (`catalog_service.py:179`), bounded by an 8 s deadline (`catalog_service.py:169`), executed through `_catalog_pool` (`max_workers=4`). There is no `request_id`/`is_current` guard, so a superseded call cannot be cancelled and every concurrent caller occupies a catalogue worker.
- **Cause:** the method was written as a direct, synchronous wrapper around a service method that is designed for an asynchronous, cancellable contract.
- **Trigger conditions:** any caller of `api.get_album_tracks(...)` for an album whose catalogue verification needs the network.
- **User impact:** the bridge thread is blocked for up to 8 s. Today the method has **no JavaScript caller** (only `tests/test_catalog_verification.py:169` and `tests/test_offline_mode.py:104` use it), so the impact is latent — but the method is exposed on the bridge and reachable from any JS.
- **Evidence:**
  ```python
  # core/api.py:2244-2248
  def get_album_tracks(self, album_data: dict):
      if not isinstance(album_data, dict) or not album_data:
          return []
      result = self._catalog_service().album_details(album_data, self._core.db.get_album_tracks)
      return result.get('tracks', []) if result.get('status') == 'found' else []
  ```
  ```python
  # services/catalog_service.py:169 / 179
  deadline = _deadline if _deadline is not None else time.monotonic() + 8
  hits = self._call(lambda: yt.search(f'{artist} {title}', filter='albums', limit=8), deadline, is_current)
  ```
- **Reproduction / verification:** grep for `get_album_tracks` across the repo: only `core/api.py`, `core/database.py`, `services/*` and `tests/*` — no `.js` file references it.
- **Suggested fix:** either delete the method or give it the same asynchronous shape as `get_album_details` (`_search_executor` + `request_id` + `album_details_ready`).
- **Fix side effects:** removing a public bridge method is a breaking change for any external caller; the tests would need updating.
- **Discovered by:** A

---

#### F-WN-06-10  [P3] — The `except TypeError` fallback around `srv.search(..., result_type=...)` can execute the provider search twice

- **File:** `core/api.py:2217-2225`.
- **Confirmed:** hypothesis
- **Description:** the `TypeError` handler is intended to cover providers that do not accept `result_type` (SoundCloud). But `TypeError` is also the error a provider raises from **inside** its `search()` body. In that case the fallback re-invokes `srv.search(query, callback=..., error_callback=...)`, i.e. the provider search runs a second time, this time without the requested `result_type`, and the second answer is merged into the result list.
- **Cause:** the fallback distinguishes "signature mismatch" from "runtime error" by exception type only; argument binding errors and body errors share the type.
- **Trigger conditions:** a provider whose `search()` body raises `TypeError` before its own `except Exception` handler. All current providers wrap their body in `except Exception`, so the fallback is currently unreachable — hence *hypothesis*.
- **User impact:** duplicate provider traffic and a duplicated/mixed result set.
- **Evidence:**
  ```python
  # core/api.py:2219-2223
  elif result_type:
      try:
          srv.search(query, result_type=result_type, callback=_on_success, error_callback=_on_error)
      except TypeError:
          srv.search(query, callback=_on_success, error_callback=_on_error)
  ```
- **Reproduction / verification:** would need a provider that leaks a `TypeError` from its body; not reproducible with the current provider implementations. A robust check is `inspect.signature(srv.search).parameters` before the call.
- **Suggested fix:** decide the call shape from the signature (`inspect.signature`) instead of catching `TypeError`.
- **Fix side effects:** `inspect.signature` on a bound method of a C-implemented callable can raise; keep the `TypeError` fallback as a last resort but guard it with a “has the search already started?” flag.
- **Discovered by:** A

---

### 3. Clean areas

Checked and found correct (brief):

- **Provider failure isolation in `search`** — CONFIRMED by execution: with `youtube` and `soundcloud` both raising and `spotify` succeeding, all four `search_results` chunks were emitted and `search_completed` still fired (`repro_wn06_b.py`). A single provider 500 does not kill the search.
- **Per-provider timeout** — `PROVIDER_SEARCH_TIMEOUT = 6.0` (`core/api.py:61`), 8 s for SoundCloud (`core/api.py:2197`); the `threading.Timer` is armed before the provider call and cancelled in `_finish` (`core/api.py:2183`). A provider that never calls back cannot hang the UI.
- **Stale-result guard** — the `_search_generation` counter (`core/api.py:2090-2096`) plus `is_current()` in `emit_results`/`mark_done` correctly drop the results of a superseded query; verified by `tests/test_api_search.py:46-74`.
- **Field-name contract between the bridge and `search.js`/`events.js`** — verified field by field. `search_results` → `{query, source, type, tracks, offline}` matches `search.js:330-382`; `search_completed` → `{query, source}` is turned into `{source:'__completion__'}` by `events.js:134-136`; `album_details_ready` → `{status, verified, album, tracks, request_id}` matches `search.js:597-620` and `search.js:712-731`. **No divergence found.**
- **`get_album_details` request-id guard** — `self._album_request_id` is set under `_window_op_lock` and re-checked before the emit (`core/api.py:2253-2263`); the JS compares `event.detail.request_id` with the id it sent (`search.js:610`). Pinned by `tests/test_catalog_verification.py:158-169`.
- **`_catalog_service()`** — the instance is created under `_window_op_lock` (`core/api.py:2236-2242`), so the lazily-created `CatalogService` is not built twice under concurrency.
- **Empty album / unknown album** — `CatalogService.album_details` returns `{'status':'not_found', 'tracks': []}` for an unknown source or a non-album browse id (`catalog_service.py:218`, `:223`, `:249`); `get_album_tracks` maps anything that is not `status == 'found'` to `[]` (`core/api.py:2248`).
- **SQL injection / wildcard handling in the local search** — `_like_pattern` escapes `\`, `%` and `_` and declares `ESCAPE '\'` (`core/database.py:1349-1364`); the FTS5 path quotes and doubles every `"` (`core/database.py:1372-1376`) and falls back to LIKE on any FTS error (`core/database.py:1390-1391`). Special characters, `%`, `_` and quotes in a query cannot widen the match. Cyrillic/non-ASCII queries are handled correctly (percent-encoding in the providers, `unicode61` FTS tokenisation, no ASCII-only assumptions).
- **`download_track` input validation** — a non-dict / empty payload returns `False` (`core/api.py:2296-2297`); a missing `source_id` is refused with a `download_failed` event and a batch-denominator correction (`core/api.py:2337-2344`); the batch denominator is decremented exactly once per rejected item (`queue_download` already decrements on the duplicate paths, and `download_track` does **not** decrement again — `core/api.py:2356-2359`).
- **`import_external_playlist` head** — the URL is extracted from arbitrary pasted text and then validated with `_is_ssrf_safe_url` **before** the importer is touched (`core/api.py:2364-2367`); `_is_ssrf_safe_url` rejects non-http(s) schemes, loopback/private/link-local/reserved addresses (including the decimal integer form) and hostnames that resolve to a private address (`core/api.py:161-195`). Unsupported URLs are rejected with a user-facing message, and the importer is only consulted for a supported URL.
- **Offline branches** — `get_library`, `get_favorites`, `get_downloaded_tracks` and `get_favorite_tracks` all switch to `offline_library` / `available_tracks` in offline mode (`core/api.py:2269-2270`, `:2279-2280`, `:2729-2730`), so only locally available files are offered while offline.
- **Missing-file handling is consistent for the “downloaded” list** — `get_downloaded_tracks` filters out rows whose file no longer exists on disk (`core/api.py:2289-2291`); verified by execution (`repro_wn06_b.py`: 2 downloaded rows → 1 returned).
- **The download is genuinely enqueued, not merely marked** — `queue_download` inserts into `download_queue` and appends to the in-memory queue (`core/downloader.py:388-410`), and the processor thread picks it up (`core/downloader.py:437-471`); the execution trace in `repro_wn06.py` shows the file actually produced on disk and `download_complete` emitted.

---

### 4. Coverage gaps

- **No live run.** The app was never started and no network call was made. Provider behaviour (YouTube / SoundCloud / Spotify / iTunes responses, timeouts, DRM failures) was read from source, not exercised. The catalogue and provider areas (WN-19..WN-21, WN-24) were only entered far enough to establish the result shapes and the `request_id`/timeout contracts.
- **The pywebview thread model was not verified** against the installed version (the interpreter reports `webview.__version__` as unavailable). Consequently I could not confirm whether a JS API call runs on the UI thread or on a dedicated bridge thread, which decides how blocking a synchronous bridge method such as `get_album_tracks` (F-WN-06-9) or `get_library` (F-WN-06-5) actually is for the window.
- **The UI was not exercised in a browser.** The spinner findings (F-WN-06-2, F-WN-06-3) are derived from the JS source (`utils.js`, `events.js`) and the event payloads, not from a running WebView. A DOM-level check in `tools/visual_guard` or a WebView2 run would confirm them end to end.
- **`get_library` payload size was not measured** — no library-size threshold at which the unbounded payload becomes visibly slow was established (F-WN-06-5 is based on the absence of any limit in the SQL and the bridge signature).
- **F-WN-06-1 was reproduced at the bridge level**, using the exact dict shape emitted by `services/catalog_service.py:244`. The full UI path (search → album modal → download button → `window.NeDotify.downloadTrack`) was traced by reading `search.js`/`utils.js`/`main.js` but not executed.
- **`services/track_resolver.py` was not reviewed** — it is not reachable from `core/api.py` (no import or attribute access); it is used by `core/downloader.py:515` (WN-13) and `services/recommendation_service.py:56` (WN-23).
- **Batch-download paths were not audited** (`start_batch` / `batch_download_progress` / `cancel_batch`): they belong to WN-10/WN-13. Only the `_decrement_batch_total_for_dedup` interaction with `download_track` was checked, and it is correct.
- **`import_external_playlist` was reviewed only for its head** (URL extraction + SSRF guard, `core/api.py:2362-2389`); the persistence/rollback body belongs to WN-07 and was not assessed.
