## AREA WN-24 — Catalog, artist, playlist-import, smart-playlist services — ROLE A

### 1. Scope reviewed

Files opened (path: line ranges actually read):

- `services/catalog_service.py` — L1–251 (whole file: `credited_to` L18–23, `CatalogService` L26–251: `_call` L34–42, `_cached` L44–70, `_artist_candidates` L72–101, `resolve_artist` L103–151, `preview_artists` L153–166, `album_details` L168–251)
- `services/artist_service.py` — L1–388 (whole file: `ArtistService` L38–388: `_best_thumbnail` L83–98, `_artists_label` L100–103, `_normalize_album` L105–131, `_collect_albums` L133–169, `_search_albums_by_artist` L171–194, `_translate_bio` L196–219, `_collect_tracks` L221–317, `_collect_top_tracks` L319–321, `_resolve_channel_id` L323–325, `get_avatars` L329–339, `get_profile` L341–388)
- `services/playlist_import_service.py` — L1–345 (whole file: `PlaylistImportError` L13, `UnsupportedPlaylistService` L18, `PlaylistImportService` L23–345: `resolve` L39–58, `_resolve_youtube` L60–124, `_resolve_soundcloud` L126–177, `_enrich_soundcloud_tracks` L179–217, `_resolve_local_file` L219–345)
- `services/smart_playlists.py` — L1–177 (whole file: `SmartPlaylistService` L6–177: `normalize_rule` L20–51, `_name` L53–57, `_id` L59–69, `_definition` L71–76, `list` L78–89, `create` L91–104, `update` L106–119, `delete` L121–126, `tracks` L128–177)

Callees / collaborators traced into other areas:

- `services/music_matching.py` L21–52 (`normalize`, `similarity`, `credits`, `artist_matches`) — **owner: WN-18**. This is the root cause of F-1/F-2/F-10; the defect is *reported here* because the breakage surfaces in WN-24 code, but the fix belongs in WN-18. Not re-reviewed as a WN-18 finding to avoid double-reporting.
- `services/artist_identity.py` L9–63 (`name_key`, `artist_aliases`, `canonical_artist`, `artist_binding`) — WN-18, read only.
- `services/itunes_gateway.py` L1–93 (`ITunesGateway.get`, `CatalogueUnavailable`) — WN-21, read only (read in full).
- `services/base_service.py` L60–199 (`_SharedExecutor`, `BaseMusicService._cache_lock`, `_executor`, `submit`) — WN-18, read only.
- `core/api.py` L90–299 (`_is_ssrf_safe_url` L161–195, `_extract_first_url` L201–220), L2230–2448 (`_catalog_service` L2234–2242, `get_album_tracks` L2244–2248, `get_album_details` L2250–2265, `import_external_playlist` L2362–2414), L3477–3535 (`get_artist_profile`, `get_artists_avatars`), L4190–4217 (`_smart_playlists`, `create/update/delete/get_smart_playlist_tracks`) — WN-03/WN-07/WN-09/WN-10, read only.
- `core/database.py` L213–256 (tracks/playlists schema), L371–378 (`is_downloaded` migration), L414–423 (`smart_playlists` table), L1054–1143 (`add_track`), L1260–1276 (`ensure_track_exists`), L1470–1482 (`get_album_tracks`), L1867–1890 (`create_playlist_ex`), L1950–1970 (`add_to_playlist`), L2001–2016 (`get_smart_playlist_tracks`) — WN-12, read only.
- `core/offline.py` L55–77 (`available_tracks`) — WN-15, read only.
- `ui/web_new_v2/js/smart-playlists.js` L24–68, `ui/web_new_v2/js/artist_profile.js` L381–426, `ui/web_new_v2/js/library.js` / `library-view.js` / `profile.js` / `player.js` (rendering of playlist names) — WN-32, read only, for the sanitisation question only.
- `services/youtube_service.py` L190–269 (`_ytmusic` client + 6 s socket timeout) — WN-19, read only.
- `.venv_win/Lib/site-packages/ytmusicapi/` `mixins/browsing.py` L139–305 (`get_artist` return shape), L520–614 (`get_album` → `album["tracks"] = parse_playlist_items(...)`), `ytmusic.py` L228–233 (30 s default timeout) — read only, to confirm the exact data shapes the code consumes.
- `.venv_win/Lib/site-packages/yt_dlp/` — grepped for a private-IP/SSRF guard (none found).

Reproduction harness: three scratch scripts under `C:\Users\Артур\AppData\Local\Temp\opencode\audit_reports\_wn24_probe{,2,3}.py` (outside the repo). No repo file was modified.

### 2. Findings

#### F-WN-24-1  [P1] — `credited_to` / `artist_matches` split asymmetry: an artist whose own name contains "," or "&" is never credited to themselves
- **File:** `services/catalog_service.py:18-23`, `services/catalog_service.py:236`; root cause `services/music_matching.py:38-45` + `services/music_matching.py:48-52` (owner: WN-18)
- **Confirmed:** yes
- **Description:** `credits()` splits a *string* on `,` `&` `feat.`/`ft.`/`featuring`/`x`, but for a *list of dicts* it does **not** split — it takes `p.get('name')` verbatim. `credited_to()` always compares a string `artist_name` against the list form `item['artists']`. So the two sides are tokenised differently: the wanted side is split, the offered side is not. An artist whose YouTube Music entity is a single artist literally named "Earth, Wind & Fire" produces wanted tokens `{earth, wind, fire}` vs offered `{earth, wind & fire}` → no intersection → **the artist is not credited to their own releases**.
- **Cause:** asymmetric tokenisation in `music_matching.credits()` (list branch does not split on separators), not in `credited_to` itself.
- **Trigger conditions:** the artist/band name contains `,`, `&`, `feat.`, `ft.`, `featuring` or a standalone `x` AND the compared item carries no usable channel id (so the id shortcut in `credited_to` cannot be taken), or the comparison is `artist_matches(album['artist'], people)` inside `album_details`.
- **User impact:** `get_album_details` / `get_album_tracks` answer `status='not_found'`, error *"Название или исполнитель альбома не совпадают"*, `tracks=[]` → the album view of such an artist is permanently empty even though the ids match. The artist page's discography (`_collect_albums` → `credited_to`) drops the same albums when the shelf item has no artist id.
- **Evidence:**
  ```python
  # services/catalog_service.py:236
  if (title and similarity(title, actual_title) < .85) or (artist and not artist_matches(artist, people, self.settings)):
      return {'status': 'not_found', 'error': 'Название или исполнитель альбома не совпадают', 'tracks': []}
  ```
  ```python
  # services/music_matching.py:41-45
  return [name.strip() for name in ... ]                      # list branch: NO split
  return [p.strip() for p in re.split(r'\s*(?:,|&|\bfeat\.?|\bft\.?|\bfeaturing|\bx\b)\s*', ...)]  # str branch: splits
  ```
- **Reproduction / verification:** `_wn24_probe.py` (real `credited_to`/`artist_matches`, no mocks):
  ```
  credited_to({'artists': [{'name': 'Earth, Wind & Fire'}]}, 'Earth, Wind & Fire') = False
  credited_to({'artists': [{'name': 'Artist feat. Guest'}]},  'Artist feat. Guest')  = False
  credits('Earth, Wind & Fire')      = ['Earth', 'Wind', 'Fire']
  credits([{'name':'Earth, Wind & Fire'}]) = ['Earth, Wind & Fire']
  ```
  End-to-end through `CatalogService.album_details` with a fake YTMusic client (`_wn24_probe2.py`):
  ```
  album_details({'source':'youtube','source_id':'MPRE-b','title':'Rock the Boat',
                 'artist':'Earth, Wind & Fire','artists':[{'name':'Earth, Wind & Fire','id':'UCband'}],
                 'artist_channel_id':'UCband'})
     status = not_found   error = "Название или исполнитель альбома не совпадают"   tracks = []
  control (same album, artist 'Kyuss')  ->  status = found   tracks = 1
  ```
  Note the id gate at L234 passes (ids intersect) and is *not* short-circuited — the name gate still rejects.
- **Suggested fix:** tokenise both sides identically — apply the separator split to the list branch as well (or normalise the wanted side to the offered side's form) in `music_matching.credits()`; alternatively compare the joined offered label against the wanted label with `similarity()` when the id gate already proved identity.
- **Fix side effects:** making the offered side split will also make a *collaboration* entry ("Artist & Other") match the single artist "Artist" — that changes `credited_to` semantics in the other direction (see F-2) and must be settled together with the id gate.
- **Discovered by:** A

#### F-WN-24-2  [P1] — Same asymmetry in the opposite direction: the album artist gate accepts a *different* artist's album
- **File:** `services/catalog_service.py:230-237`; root cause `services/music_matching.py:38-45` (owner: WN-18)
- **Confirmed:** yes
- **Description:** Because the wanted side is split and the offered side is not, a multi-token artist name matches a *single-token* artist. `artist_matches('Earth, Wind & Fire', [{'name':'Fire'}])` → wanted `{earth, wind, fire}` ∩ offered `{fire}` → **True**. When the album dict carries no `artists[]` ids and no `artist_channel_id`, the id gate at L234 is skipped (`if wanted_ids and offered_ids and ...`) and the name gate alone approves the album.
- **Cause:** same tokenisation asymmetry as F-1, used as a permissive rather than a restrictive comparison.
- **Trigger conditions:** the album dict passed to `album_details` has no `artists` / `artist_channel_id` (e.g. a DB row, a hand-built dict, or the `source='local'` path where `album.get('artist')` is a joined string), **and** the target artist name contains `,`/`&`/`feat.`
- **User impact:** the user opens artist "Earth, Wind & Fire" and is shown the album of "Fire"; every track in it can then be downloaded into the user's library (this is the "wrong track is downloaded" path). The `verified: True` flag at L250 asserts the album was verified against the catalogue.
- **Evidence:**
  ```python
  # services/catalog_service.py:230-235
  wanted_ids = {str(p.get('id') or p.get('browseId')) for p in album.get('artists') or [] ...}
  if album.get('artist_channel_id'):
      wanted_ids = {str(album['artist_channel_id'])}
  offered_ids = {...}
  if wanted_ids and offered_ids and not wanted_ids.intersection(offered_ids):
      return {'status': 'not_found', 'error': 'Альбом принадлежит другому исполнителю', 'tracks': []}
  ```
  ```python
  # services/catalog_service.py:250
  return {'status': 'found', 'verified': True, 'album': details, 'tracks': tracks}
  ```
- **Reproduction / verification:** `_wn24_probe3.py` — album dict **without** ids, real `CatalogService.album_details` + fake YTMusic:
  ```
  yt.albums['MPRE-f'] = {'title':'Single','artists':[{'name':'Fire','id':'UCfire'}],
                         'tracks':[{'videoId':'vf','title':'Track F'}]}
  album_details({'source':'youtube','source_id':'MPRE-f','title':'Single','artist':'Earth, Wind & Fire'})
     status = found   tracks = ['Track F']
  ```
  and the primitive-level check: `credited_to({'artists':[{'name':'Fire'}]}, 'Earth, Wind & Fire') = True`.
- **Suggested fix:** resolve F-1 and F-2 together by making the two sides tokenise identically, and make the id gate *mandatory* (not conditional on `wanted_ids and offered_ids`) whenever the album dict supplies an artist identity.
- **Fix side effects:** tightening the name gate will re-admit the F-1 false negatives unless both directions are fixed in one change.
- **Discovered by:** A

#### F-WN-24-3  [P1] — Playlist import: one malformed `duration` in a JSON playlist silently replaces the whole playlist with a single garbage entry
- **File:** `services/playlist_import_service.py:233-254` (JSON branch) and `services/playlist_import_service.py:256-345` (M3U fallback it falls through to)
- **Confirmed:** yes
- **Description:** The JSON branch builds every track inside one `try: … except Exception: pass` block. `float(item.get("duration", 0))` raises `ValueError`/`TypeError` for a duration written as `"3:45"`, `null`, or a non-numeric string. The exception discards the **whole** `tracks` list (already parsed for the good items) and control falls through to the M3U/text parser, which then treats each line of the JSON document as a track. The result is a one-entry "playlist" whose title is the entire raw JSON text, artist `"Unknown Artist"`, `source="youtube"`, `source_id=<the whole JSON blob>` — and the playlist *name* degrades from the JSON `"name"` field to the file basename.
- **Cause:** per-item parsing is wrapped in a single coarse `try/except: pass` whose failure path falls through to a *different* parser instead of raising a typed error.
- **Trigger conditions:** any JSON playlist file (the app's own export format included) containing one track whose `duration` is not a number or numeric string.
- **User impact:** the import "succeeds" (`success: True`, `imported_count: 1`) but the user's playlist contains a single unplayable pseudo-track instead of their music. Silent data corruption on the import path — the user is not told anything went wrong.
- **Evidence:**
  ```python
  # services/playlist_import_service.py:239-254
  for item in items:
      if isinstance(item, dict):
          tracks.append({... "duration": float(item.get("duration", 0)), ...})
      ...
  if tracks:
      return {...}
  except Exception:
      pass          # <- swallows the ValueError and falls through to the text parser
  ```
- **Reproduction / verification:** `_wn24_probe2.py` — real `PlaylistImportService.resolve()` on a temp file:
  ```
  JSON: {"name":"My list","tracks":[{"title":"Good One",...,"duration":120.0,...},
                                     {"title":"Bad One",...,"duration":"3:45",...}]}
  resolved name: bad
  track: {'title': '{"name": "My list", "tracks": [...]}', 'artist': 'Unknown Artist',
          'source': 'youtube', 'source_id': '{"name": "My list", "tracks": [...]}'}
  ```
  Same result with `"duration": null`.
- **Suggested fix:** coerce the duration per item inside the loop (`float(...)` in a try/except that defaults to `0.0`), and make a failed JSON parse raise `PlaylistImportError` instead of falling through to the text parser.
- **Fix side effects:** making the JSON branch raise changes the error surface for genuinely malformed JSON (currently it silently degrades to the text parser); that is the desired behaviour but it must be surfaced to the UI.
- **Discovered by:** A

#### F-WN-24-4  [P2] — A remote `.m3u`/`.m3u8`/`.json`/`.txt` playlist URL is never fetched — it is treated as a local path
- **File:** `services/playlist_import_service.py:46`
- **Confirmed:** yes
- **Description:** `resolve()` dispatches on `os.path.exists(target) or target.endswith((".m3u", ".m3u8", ".json", ".txt"))` → `_resolve_local_file(target)`, which does `if not os.path.exists(target): raise PlaylistImportError(f"Файл плейлиста не найден: {target}")`. The service contains **no** HTTP fetch for a remote playlist document, so the advertised "M3U/M3U8" import only works for a file that already exists on this machine.
- **Cause:** the extension branch was written for the on-disk case; no URL-fetch counterpart exists.
- **Trigger conditions:** the user pastes an `https://…/playlist.m3u8` link (the canonical shape produced by other players and by this app's own `export_playlist`).
- **User impact:** the import fails with *"Файл плейлиста не найден: https://…/playlist.m3u8"* — the URL is echoed back as if it were a path. Combined with the bridge's `_is_ssrf_safe_url` scheme check (`core/api.py:2365`), a local path is rejected too, so **the app cannot import its own exported `.m3u8` by either route**.
- **Evidence:**
  ```python
  # services/playlist_import_service.py:45-47
  # 1. Local file or M3U/JSON text content
  if os.path.exists(target) or target.endswith((".m3u", ".m3u8", ".json", ".txt")):
      return self._resolve_local_file(target)
  ```
  ```python
  # services/playlist_import_service.py:221-222
  if not os.path.exists(target):
      raise PlaylistImportError(f"Файл плейлиста не найден: {target}")
  ```
- **Reproduction / verification:** `_wn24_probe2.py` dispatch table:
  ```
  https://example.com/list.m3u8 -> PlaylistImportError: Файл плейлиста не найден: https://example.com/list.m3u8
  https://example.com/list.txt  -> PlaylistImportError: Файл плейлиста не найден: https://example.com/list.txt
  ```
- **Suggested fix:** split the dispatch — remote `http(s)` targets with a playlist-file extension must be downloaded (through the same SSRF-checked path) before parsing; keep the on-disk branch for real paths.
- **Fix side effects:** introduces a network fetch into the importer → it must be SSRF-checked again at fetch time and must be size/time bounded; the "rejected local path" part of the bridge (`core/api.py:2365`) is owned by WN-07 and would need to change for local-path import.
- **Discovered by:** A

#### F-WN-24-5  [P2] — The imported track list is uncapped: a large playlist is imported one DB transaction per track inside one bridge call
- **File:** `services/playlist_import_service.py:79-124` (`_resolve_youtube`), `services/playlist_import_service.py:144-177` (`_resolve_soundcloud`); caller `core/api.py:2389-2396`
- **Confirmed:** yes
- **Description:** Neither `_resolve_youtube`, `_resolve_soundcloud` nor `_resolve_local_file` imposes a maximum on the number of returned tracks. `core/api.py::import_external_playlist` then loops over every track and, for each one, calls `db.ensure_track_exists(track)` (one transaction) followed by `db.add_to_playlist(...)` (a second transaction that also computes `MAX(position)+1`). A YouTube playlist may hold several thousand entries, and `SoundCloudService`/yt-dlp flat extraction returns all of them.
- **Cause:** no bound between "how many tracks a remote service may return" and "how many rows the bridge will write synchronously".
- **Trigger conditions:** importing a large public playlist (YouTube allows up to 5000 entries).
- **User impact:** the bridge call stays busy for minutes; the user's `tracks` and `playlist_tracks` tables grow by 2×N rows; the per-track `MAX(position)` scan makes the insert cost superlinear. The bridge method returns only at the very end, so the UI shows nothing until the whole import finished.
- **Evidence:**
  ```python
  # core/api.py:2389-2396
  added_count = 0
  for track in tracks:
      if not isinstance(track, dict):
          raise ValueError("Resolver вернул некорректную структуру трека")
      track_id = self._core.db.ensure_track_exists(track)
      if not track_id or not self._core.db.add_to_playlist(playlist_id, track_id):
          raise RuntimeError("Не удалось добавить все треки в локальный плейлист")
      added_count += 1
  ```
- **Reproduction / verification:** static — there is no `MAX_TRACKS`/`[:N]`/counter limit anywhere in `services/playlist_import_service.py`; `core/database.py:1950-1967` shows one `with conn:` transaction per `add_to_playlist` call.
- **Suggested fix:** cap the number of imported tracks in the importer (with an explicit "playlist truncated" notice) and/or batch the inserts (`db.add_tracks_to_playlist` already exists, `core/database.py:1972`).
- **Fix side effects:** a cap silently drops tracks; the UI must show the truncation count.
- **Discovered by:** A

#### F-WN-24-6  [P2] — The artist discography collector has no deadline and ignores `is_current()`, so a superseded artist profile keeps hammering YouTube Music
- **File:** `services/artist_service.py:133-169` (`_collect_albums`), `services/artist_service.py:221-317` (`_collect_tracks`), `services/artist_service.py:341-388` (`get_profile`)
- **Confirmed:** yes
- **Description:** `CatalogService` carefully bounds every YouTube Music call through `_call(fn, deadline, is_current)` (deadline + cancellation check). `ArtistService` does **not** use that mechanism: `_collect_albums` and `_collect_tracks` call `yt.get_artist_albums`, `yt.search`, `yt.get_playlist` and `yt.get_album` directly, with no time budget and without ever consulting the `is_current` predicate that `get_profile` received from the bridge. Up to ~9 sequential round trips are issued (2 shelf continuations + 1 album search + 1 songs playlist + 1 songs search + up to 4 album track fetches); the YouTube Music session has a 6 s socket timeout (`services/youtube_service.py:204`), so the worst case is roughly a minute of work for a profile nobody is waiting for.
- **Cause:** the artist service bypasses the catalogue's deadline/cancellation wrapper and only checks `is_current()` once, after everything has been collected.
- **Trigger conditions:** the user opens artist A and then artist B quickly (or repeatedly opens different artists). Each superseded profile keeps running to completion.
- **User impact:** wasted YouTube Music quota and a stalled shared executor. `ArtistService.get_profile` runs on `BaseMusicService._executor`, a **class-level pool of 8 workers shared by every music service** (`services/base_service.py:124`); 8 superseded artist profiles occupy all of them and every other provider call (search, stream resolution, lyrics) queues behind them.
- **Evidence:**
  ```python
  # services/artist_service.py:157
  _absorb(yt.get_artist_albums(channel_id, params, limit=MAX_ALBUMS))
  # services/artist_service.py:179
  hits = yt.search(artist_name, filter="albums", limit=40)
  # services/artist_service.py:282
  playlist_data = yt.get_playlist(browse_id, limit=100)
  # services/artist_service.py:291
  search_hits = yt.search(artist_name, filter="songs", limit=50)
  # services/artist_service.py:309
  alb_data = yt.get_album(alb_id)
  ```
  `is_current` appears only at `services/artist_service.py:345` and `:381`/`:384`, i.e. *after* the collection.
- **Reproduction / verification:** static — `grep -n "is_current" services/artist_service.py` shows the predicate is never passed into `_collect_albums`/`_collect_tracks`; both methods have no `is_current` parameter at all.
- **Suggested fix:** route the ytmusicapi calls through `CatalogService._call` (or give the collector the same deadline/`is_current` pair) and abort the remaining collection as soon as the request is superseded.
- **Fix side effects:** the catalogue pool has only 4 workers (`services/catalog_service.py:14`); routing artist work through it could serialise artist pages behind album lookups.
- **Discovered by:** A

#### F-WN-24-7  [P2] — Ambiguous / unavailable artist resolutions are never cached, so the home feed re-runs up to 30 serial catalogue lookups (through the globally rate-limited iTunes gateway) on every load
- **File:** `services/catalog_service.py:63-66` (`_cached`), `services/artist_service.py:329-339` (`get_avatars`), `services/itunes_gateway.py:21-22` and `50-63` (global rate limiter)
- **Confirmed:** yes
- **Description:** `_cached` stores only `status in ('found', 'not_found')`. `'ambiguous'` (the artist exists but needs a user choice) and `'unavailable'` (network failure) are re-fetched every time. `ArtistService.get_avatars` resolves up to 30 names **serially inside one task**, each with its own 8 s deadline, and `_artist_candidates` falls back to the iTunes Search API whenever YouTube Music returns no hit. `ITunesGateway` serialises *every* iTunes request in the app behind a 3.5 s interval and an 18-requests-per-minute cap, and the same gateway is used by the spotify/itunes album lookups (`services/catalog_service.py:196`).
- **Cause:** the cache policy treats "ambiguous" as a transient value although it is a stable, user-actionable fact; the avatar batch is a serial loop over a rate-limited global gateway.
- **Trigger conditions:** any home-feed render with artist names that are not yet resolved (`ui/web_new_v2/js/home.js:618`, `js/search-discovery.js:63`), or a host of artists that YouTube Music cannot resolve (which is exactly the case that hits the iTunes fallback).
- **User impact:** avatars arrive late (the `artists_avatars_ready` event is the only delivery), one worker of the shared 8-thread executor is pinned for up to 4 minutes, and the app-wide iTunes budget is burned on avatar lookups, delaying every album detail lookup that needs iTunes.
- **Evidence:**
  ```python
  # services/catalog_service.py:63-64
  if result.get('status') in ('found', 'not_found'):
      self._results[key] = (time.monotonic() + (900 if result['status'] == 'found' else 60), copy.deepcopy(result))
  ```
  ```python
  # services/artist_service.py:331-335
  for name in list(dict.fromkeys(n.strip() for n in names or [] if isinstance(n, str) and n.strip()))[:30]:
      resolved = self.catalog.resolve_artist(name)
      raw = resolved.get('profile_data') or {}
      mapping[name] = self._best_thumbnail(raw) if resolved.get('status') == 'found' and resolved.get('source') == 'youtube' else ''
  ```
  ```python
  # services/itunes_gateway.py:21-22
  INTERVAL = 3.5
  PER_MINUTE = 18
  ```
- **Reproduction / verification:** static — confirmed that `'ambiguous'` never reaches the `self._results[...]` assignment, and that `get_avatars` has no `ThreadPoolExecutor`/batch fan-out (contrast `services/playlist_import_service.py:197-204`, which does use one).
- **Suggested fix:** cache `'ambiguous'` with a short TTL (it is stable until the user binds a different identity), and resolve the avatar batch concurrently with a bounded pool while respecting the iTunes budget.
- **Fix side effects:** caching `'ambiguous'` means a later binding change is not picked up until the TTL expires (the binding path in `core/api.py` already writes the alias map into the cache key, `services/catalog_service.py:114`).
- **Discovered by:** A

#### F-WN-24-8  [P3] — A smart playlist whose stored `rule_json` is corrupt or uses an old schema disappears from the list and raises out of the bridge when opened
- **File:** `services/smart_playlists.py:71-76` (`_definition`), `services/smart_playlists.py:134-137` (`tracks`), `services/smart_playlists.py:78-89` (`list`); caller `core/api.py:4214-4217`
- **Confirmed:** yes
- **Description:** `_definition()` re-validates the persisted rule with `normalize_rule(json.loads(...))`. `list()` wraps that in `except (TypeError, ValueError): continue`, so an unreadable collection is silently skipped. `tracks()` calls `_definition(...)` with **no** guard, so the same collection raises straight through `AppApi.get_smart_playlist_tracks` into pywebview as an unhandled exception (JSONDecodeError / ValueError) instead of a structured error.
- **Cause:** inconsistent error handling between the two readers of the same persisted column.
- **Trigger conditions:** `rule_json` is not valid JSON, or is valid JSON that no longer validates against the current rule schema (e.g. a rule field renamed in a later version). The service itself always writes valid JSON, so this needs an external writer or a schema migration.
- **User impact:** the collection vanishes from the smart-playlist list without any message, and clicking through to it (by id, e.g. a stale bookmark or a deep link) produces a rejected promise instead of an empty collection.
- **Evidence:**
  ```python
  # services/smart_playlists.py:84-88
  for row in rows:
      try:
          definitions.append(self._definition(row))
      except (TypeError, ValueError):
          continue
  ```
  ```python
  # services/smart_playlists.py:134-137
  definition = self._definition(self.db.conn.execute(
      "SELECT * FROM smart_playlists WHERE id = ?", (playlist_id,)
  ).fetchone())
  ```
- **Reproduction / verification:** `_wn24_probe3.py` — a real `SmartPlaylistService` over an in-memory DB with two bad rows:
  ```
  list() -> []                      # both rows silently skipped
  tracks(1) -> JSONDecodeError: Expecting property name enclosed in double quotes: line 1 column 2 (char 1)
  tracks(2) -> ValueError: Неизвестное правило плейлиста
  ```
- **Suggested fix:** have `tracks()` catch the same exceptions and return an explicit "collection unavailable" result (or repair the row), and surface skipped collections in `list()` instead of dropping them silently.
- **Fix side effects:** surfacing the broken row changes `list()`'s contract, which `tests/test_smart_playlists.py:92-98` currently pins as "silently skipped" — the test would need updating.
- **Discovered by:** A

#### F-WN-24-9  [P3] — `ArtistService` carries a dead avatar cache: the documented 7-day TTL does not exist and a second lock is opened for nothing
- **File:** `services/artist_service.py:33-35`, `services/artist_service.py:46-49`, `services/artist_service.py:319-325`
- **Confirmed:** yes
- **Description:** `AVATAR_TTL = 7 * 24 * 3600` with the comment *"Resolved avatar URLs live for a week … the home feed re-requests the same top artists on every load"*, plus `self._avatars` and `self._avatars_lock`, are **never read or written** — `get_avatars` resolves through `CatalogService.resolve_artist` instead. The effective avatar TTL is the catalogue's 900 s (`found`) / 60 s (`not_found`). `_collect_top_tracks` (L319) and `_resolve_channel_id` (L323) are likewise never called anywhere in the repository.
- **Cause:** the avatar cache was superseded by the catalogue cache without the old fields being removed.
- **Trigger conditions:** always — the fields exist from construction.
- **User impact:** none directly; the risk is the misleading contract. `AGENTS.md` requires that a new shared field joins its class's existing lock — `_avatars_lock` is a *second* lock in a class that already owns `_profiles_lock` and the inherited `_cache_lock`. It is harmless today only because nothing uses it.
- **Evidence:**
  ```python
  # services/artist_service.py:33-35
  #: Resolved avatar URLs live for a week: channel photos change rarely, and the
  #: home feed re-requests the same top artists on every load.
  AVATAR_TTL = 7 * 24 * 3600
  ```
  ```python
  # services/artist_service.py:48-49
  self._avatars: Dict[str, Any] = {}
  self._avatars_lock = threading.Lock()
  ```
- **Reproduction / verification:** repo-wide grep for `_avatars|AVATAR_TTL|_collect_top_tracks|_resolve_channel_id` returns only the declarations in `services/artist_service.py` (L35, L48, L49, L319, L323) — no reader, no caller.
- **Suggested fix:** delete the dead fields/constants, or implement the 7-day avatar cache in `get_avatars` and drop the reliance on the 15-minute catalogue TTL.
- **Fix side effects:** implementing the avatar cache adds a second source of truth for artist identity; the catalogue binding path would have to invalidate it.
- **Discovered by:** A

#### F-WN-24-10  [P3] — Artist names of four characters or fewer never produce "near" candidates, so the disambiguation picker stays empty
- **File:** `services/catalog_service.py:144`; root cause `services/music_matching.py:33-34` (owner: WN-18)
- **Confirmed:** yes
- **Description:** `resolve_artist` builds its fallback candidate list with `near = [h for h in candidates if similarity(name, h['name']) >= .75]`. `similarity()` returns `0.0` for *any* pair whose shorter normalised form is ≤ 4 characters (`min(len(a.replace(' ','')), len(b.replace(' ',''))) <= 4`). For a short artist name the exact-match branch still works (equality is checked first), but there is never a near-miss candidate, so a homonym such as "ABBA" vs "ABBA Band" produces no candidate list at all.
- **Cause:** a hard length floor inside `similarity()` that is meant to avoid false positives on short strings silently disables the near-match tier for short names.
- **Trigger conditions:** an artist whose canonical name is ≤ 4 characters ("U2", "ABBA", "BTS", "M83", " muse ").
- **User impact:** `resolve_artist` returns `not_found` / `unavailable` instead of `ambiguous`, so the user is never offered the "which artist do you mean?" picker that the same code path provides for longer names. The user concludes the artist does not exist.
- **Evidence:**
  ```python
  # services/music_matching.py:33-34
  if min(len(a.replace(' ', '')), len(b.replace(' ', ''))) <= 4:
      return 0.0
  ```
  ```python
  # services/catalog_service.py:144-149
  near = [h for h in candidates if similarity(name, h['name']) >= .75]
  ...
  options = exact or near
  if options:
      return {'status': 'ambiguous', 'candidates': options}
  ```
- **Reproduction / verification:** `_wn24_probe3.py`:
  ```
  similarity('ABBA','ABBA')      = 1.0
  similarity('ABBA','ABBA Band') = 0.0
  similarity('U2','U2 Live')     = 0.0
  ```
- **Suggested fix:** in `resolve_artist`, fall back to a prefix/substring candidate test when `similarity()` returns 0 for short names, or lower the floor in `similarity()` for the near-match tier only.
- **Fix side effects:** lowering the floor in `similarity()` also affects the album-title gate at `services/catalog_service.py:201`/`:236` (`similarity(title, actual_title) < .85`), which would need re-checking.
- **Discovered by:** A

#### F-WN-24-11  [P3] — The "unsupported service" message does not mention SoundCloud, which *is* supported
- **File:** `services/playlist_import_service.py:58`
- **Confirmed:** yes
- **Description:** `resolve()` handles YouTube (L50), SoundCloud (L54), and local M3U/M3U8/JSON/text files (L46), but the error raised for every other input lists only *"YouTube, M3U/M3U8, JSON и текстовых списков"*. SoundCloud — and only SoundCloud — is missing.
- **Cause:** the message was not updated when the SoundCloud branch was added.
- **Trigger conditions:** any unsupported URL (Spotify, Yandex Music, VK, `.plist`, `file://`).
- **User impact:** the user is told a supported service is unsupported, and is not told which services *are* supported. Directly visible in the UI toast for a Spotify playlist link.
- **Evidence:**
  ```python
  # services/playlist_import_service.py:53-58
  # 3. SoundCloud URL
  if "soundcloud.com" in target:
      return self._resolve_soundcloud(target)

  # Unsupported service
  raise UnsupportedPlaylistService("Поддерживается импорт плейлистов YouTube, M3U/M3U8, JSON и текстовых списков")
  ```
- **Reproduction / verification:** `_wn24_probe2.py` dispatch table: `https://open.spotify.com/playlist/...` → `UnsupportedPlaylistService: Поддерживается импорт плейлистов YouTube, M3U/M3U8, JSON и текстовых списков`.
- **Suggested fix:** list every supported scheme in the message (YouTube, SoundCloud, M3U/M3U8, JSON, text lists) and name the unsupported ones explicitly.
- **Fix side effects:** none.
- **Discovered by:** A

#### F-WN-24-12  [P3] — A nested playlist is imported as a phantom, unplayable track (no recursion, but a bogus entry)
- **File:** `services/playlist_import_service.py:80-119` (`_resolve_youtube`), `services/playlist_import_service.py:144-166` (`_resolve_soundcloud`)
- **Confirmed:** hypothesis
- **Description:** Both resolvers use `extract_flat: "in_playlist"`, so yt-dlp does **not** expand a playlist entry that is itself a playlist — there is no recursion and therefore no infinite recursion for a self-referencing playlist (that part of the design is sound). But yt-dlp still returns the nested entry as a flat item with an `id` and a `title`, and the code unconditionally turns it into a track: `source_id = entry.get('id")` (the *playlist* id), `source='youtube'`, `title` = the nested playlist's title, `artist` = "Unknown Artist". The nested playlist's own tracks are never imported and the entry is not playable.
- **Cause:** the flat-extraction result is not filtered for `_type == 'playlist'` / `entries is None`.
- **Trigger conditions:** importing a YouTube playlist that contains another playlist.
- **User impact:** the user's playlist gains an unplayable entry with the nested playlist's title; the import count is off by the number of nested playlists.
- **Evidence:**
  ```python
  # services/playlist_import_service.py:80-88
  for entry in entries:
      if not isinstance(entry, dict):
          continue
      source_id = entry.get("id")
      if not source_id:
          continue
      title = entry.get("title") or "Unknown Title"
      artist = entry.get("uploader") or entry.get("artist") or "Unknown Artist"
  ```
- **Reproduction / verification:** not observed live — the synthetic YouTube/SoundCloud URLs used in the probe failed with HTTP 400/404 before a nested entry could be produced. Missing evidence: the exact flat-extraction dict yt-dlp returns for a nested playlist entry (`_type`, `ie_key`, `id`). Confirmation: run `yt_dlp.YoutubeDL({"extract_flat": "in_playlist"}).extract_info(<real playlist containing a playlist>)` and inspect the entry.
- **Suggested fix:** skip entries whose flat payload denotes a playlist (`entry.get("_type") == "playlist"` or `entry.get("entries") is not None`), or expand them with an explicit depth limit.
- **Fix side effects:** expanding nested playlists reintroduces a recursion surface and needs a depth cap and a track cap.
- **Discovered by:** A

#### F-WN-24-13  [P3] — `CatalogService._cached` can leave a key permanently "in flight" if the result cannot be deep-copied
- **File:** `services/catalog_service.py:44-70` (`_cached`, owner path L58-70)
- **Confirmed:** hypothesis
- **Description:** The owner path sets `flight['result']`, pops `self._flights[key]` and only then calls `flight['event'].set()`. If `copy.deepcopy(result)` at L64 raises, lines 67–69 never run: the entry stays in `self._flights`, the event is never set, and the `except` clause (which only wraps `fetch()`) does not cover it. Every later caller for that key becomes a "waiter" on an event that will never fire and blocks for its full deadline (8 s) before returning `{'status': 'unavailable'}`. The key is stuck for the lifetime of the process.
- **Cause:** the result is deep-copied *inside* the critical section that is also responsible for releasing the flight, and there is no `finally` that guarantees `event.set()`.
- **Trigger conditions:** the fetched result contains an object that `copy.deepcopy` cannot handle. For `resolve_artist` the payload is the ytmusicapi JSON dict and for `album_details` it is the caller-supplied album dict — both plain data today, so the trigger is not reachable with the current call sites; it becomes reachable if a caller ever passes a non-copyable value in `album_data`.
- **User impact:** one catalogue key (an artist or an album) becomes permanently unresolvable — every future lookup of it burns its full 8 s deadline and returns "unavailable".
- **Evidence:**
  ```python
  # services/catalog_service.py:62-69
  with self._cache_lock:
      if result.get('status') in ('found', 'not_found'):
          self._results[key] = (time.monotonic() + (...), copy.deepcopy(result))   # <-- may raise
          ...
      flight['result'] = result
      self._flights.pop(key, None)
      flight['event'].set()
  ```
- **Reproduction / verification:** not reproduced — no current call site supplies an uncopyable value. Confirmation would be: call `catalog.album_details({'source':'youtube', 'source_id':'X', 'title': object()})` (a dict containing a non-copyable object) and observe that a second call for the same key returns `unavailable` after the full deadline instead of hitting the cache.
- **Suggested fix:** move the deep-copy out of the critical section and release the flight in a `finally:` block (`flight['event'].set()` must run on every path).
- **Fix side effects:** none; the copy is only needed to keep the cached value immutable.
- **Discovered by:** A

**Cross-area observations (not counted as WN-24 findings — the root cause lives elsewhere):**

- `core/api.py::import_external_playlist` (WN-07): when the import targets an **existing** playlist of the same name, `create_playlist_ex` returns `created=False` (`core/database.py:1884-1887`), and the rollback at `core/api.py:2408` only deletes playlists this call created. A failure *after* some tracks were added therefore leaves the partially imported tracks in the user's pre-existing playlist, while the bridge returns `{"success": false}`. `tests/test_api_f1_audit.py:287-301` pins only that the playlist is not deleted, not that the partial tracks are rolled back. Owner: **WN-07**.
- `core/api.py::import_external_playlist` (WN-07): the playlist name is `str(name or "").strip()` with no length cap (unlike `SmartPlaylistService._name`, which caps at 120 chars), and the description is the raw `f"Imported from {url}"`. Neither is a security problem — every playlist name is rendered through `escapeHtml` in the UI (`ui/web_new_v2/js/library.js:606,863`, `library-view.js:62,87,155`, `profile.js:103`, `player.js:1255`) and the description is never rendered at all — but the name is stored unbounded. Owner: **WN-07**.
- `services/music_matching.py::credits` / `similarity` (WN-18): the tokenisation asymmetry behind F-1/F-2 and the length floor behind F-10 live here; fixing them in WN-18 fixes WN-24's manifestations.

### 3. Clean areas

- **No SQL injection in the smart-playlist rule path.** `normalize_rule` (`services/smart_playlists.py:20-51`) accepts only a fixed key set, requires `type(value) is int` for the day rules (rejecting `"30"`, `30.0` and `True`), requires real `bool` for the flag rules, bounds the artist string at 160 chars, and validates `sort` against the fixed `SORTS` dict. Every user value is bound as a SQL parameter; the `artist` LIKE pattern is escaped correctly (backslash first, then `%` and `_`) and the `ESCAPE '\'` clause is honoured. The `ORDER BY` fragment is looked up in `SORTS`, never interpolated from user input. Verified empirically (`_wn24_probe3.py`): `artist="%"`+`"_"` matched only the literal `100%_band` and not `100xxband`; `artist="' OR 1=1 --"` matched nothing and the track count stayed at 2; a `sort` of `"title; DROP TABLE tracks"` is rejected by `normalize_rule` (pinned by `tests/test_smart_playlists.py:57-78`).
- **An invalid rule never crashes and never writes.** `normalize_rule` raises `ValueError` for every malformed input; `create`/`update` validate before touching the DB, and `_definition` re-validates on read, so a hand-edited row cannot inject a rule.
- **Pagination is honoured and hard-bounded.** `tracks()` enforces `1 <= limit <= 500` and `0 <= offset <= 100000` (`type(limit) is not int` also rejects `True`), and applies `LIMIT ? OFFSET ?` in SQL on the normal path and an equivalent Python-side slice on the offline path. The offline path pages correctly across DB fetch batches (pinned by `tests/test_smart_playlists.py:125-137`).
- **SSRF: the import URL is validated before it is fetched.** `core/api.py:2364-2367` runs `_extract_first_url` and then `_is_ssrf_safe_url` *before* `importer.resolve(url)` is called; `_is_ssrf_safe_url` (`core/api.py:161-195`) requires an `http`/`https` scheme, rejects `localhost`/`0.0.0.0`/`::1`, rejects numeric/integer IP encodings, and resolves every A/AAAA record to check that none is loopback/private/link-local/reserved/multicast. Consequently `file://…` and bare local paths (`C:/…`, `D:\…`) are rejected at the bridge — confirmed: `urlparse("C:/Music/list.m3u8").scheme == 'c'` → not in `("http","https")` → blocked. The importer itself only accepts a local path when called programmatically (`services/playlist_import_service.py:46`), which is not reachable from the UI (the UI only passes a URL — `ui/web_new_v2/js/library.js:181`, `js/settings.js:354`, `js/onboarding.js:198`).
- **No recursion in the playlist import.** `extract_flat: "in_playlist"` never expands nested playlists, so a self-referencing playlist cannot cause infinite recursion (see F-12 for the phantom-entry side effect).
- **`CatalogService` uses the inherited lock correctly.** `_cached` guards the instance-level `_results`/`_flights` with `self._cache_lock` — the *existing* class-level `RLock` from `BaseMusicService` (`services/base_service.py:125`) — rather than opening a second lock, complying with the `AGENTS.md` rule. Identical concurrent requests are single-flighted through `_flights` and share one result.
- **The catalogue never invents an identity.** `resolve_artist` returns `ambiguous` with an explicit candidate list instead of picking a fuzzy hit, distinguishes `not_found` from `unavailable`, and caches only `found`/`not_found` so a network failure is never remembered as a fact (pinned by `tests/test_catalog_verification.py:38-78`).
- **Album identity is double-checked.** `album_details` compares the album id set *and* the artist/title (`services/catalog_service.py:230-237`); the iTunes path filters out tracks belonging to other collections (pinned by `tests/test_catalog_verification.py:100-107`).
- **Album track order is stable and comes from the provider.** YouTube Music returns the album in album order (`ytmusicapi` `get_album` → `parse_playlist_items`), the iTunes path uses the lookup order, and the local path uses `ORDER BY track_number ASC, title ASC` (`core/database.py:1474-1480`).
- **The artist discography is deterministically ordered and capped.** `albums.sort(key=lambda a: (-(a.get("year") or 0), a.get("title", "")))` then `albums[:MAX_ALBUMS]` with `MAX_ALBUMS = 120` (`services/artist_service.py:168-169`).
- **The artist profile degrades gracefully.** A missing thumbnail yields `""` (the UI falls back to a generated gradient, `ui/web_new_v2/js/utils.js:578`); a missing bio yields `""` and the UI's `bio_ru || bio || ''` chain handles the itunes-source profile that omits `bio_ru`/`bio_original` (`ui/web_new_v2/js/artist_profile.js:381-390`); `_best_thumbnail` has an exception fallback.
- **The smart-playlist list/create/update/delete paths are safe.** `MAX_PLAYLISTS = 100` is enforced on create, the name is length-bounded, ids are validated (`_id` rejects bools, floats and non-canonical numeric strings), and `list()` skips unparsable rows instead of failing the whole list.
- **Playlist names and descriptions are safe to render.** Every playlist name is passed through `escapeHtml` in the UI, and the imported description (`"Imported from <url>"`) is never rendered at all.
- **Repository tests for the two most complex areas pass unchanged** (`pytest tests/test_smart_playlists.py tests/test_catalog_verification.py -q` → 35 passed), which confirms that the findings above are gaps in the existing coverage rather than known-broken behaviour.

### 4. Coverage gaps

- **No live provider traffic.** YouTube Music, iTunes, SoundCloud and yt-dlp were never exercised against the real services (the `network` marker is deselected and running the real app is out of scope). F-1/F-2/F-10 were reproduced with the *real* `credited_to`/`artist_matches`/`similarity`/`CatalogService` code plus a fake YTMusic client that returns exactly the shapes ytmusicapi 1.12.3 documents (`parse_album_header_2024` + `parse_playlist_items`, `mixins/browsing.py:596-602`); the album-shape assumption therefore rests on the library contract, not on a live response.
- **F-12** (nested playlist) and **F-13** (uncopyable result) could not be reproduced — the missing evidence is stated per finding. F-12 needs a real YouTube playlist containing a playlist; F-13 needs a call site that passes a non-deep-copyable value into `album_details`.
- **yt-dlp's redirect behaviour was not exercised.** `_is_ssrf_safe_url` validates the *initial* URL only; the importer hands the URL to yt-dlp, which follows redirects and (per a grep of `.venv_win/Lib/site-packages/yt_dlp`) contains no private-IP guard of its own. A public URL that 302-redirects to `http://127.0.0.1/…` would therefore bypass the SSRF check. This is a **hypothesis**, not a finding: the URL must still contain `youtube.com`/`youtu.be`/`soundcloud.com` to reach the yt-dlp branches (`services/playlist_import_service.py:50-55`), and the redirect target was not observed. Confirming it needs a controlled redirect server. The SSRF guard itself is owned by WN-03.
- **Not reviewed (other areas):** `core/proxy.py`, `core/downloader.py`, the DB migration path, `services/youtube_service.py` in full, and the UI modules beyond the escaping/rendering checks listed in section 1.
- **Deliberately not reported as findings:** the dead locals `credited`/`target` in `services/artist_service.py:186-189` and `:292-296` (leftovers, no behavioural effect) and the FIFO (rather than LRU) eviction in `services/catalog_service.py:65-66` — both are code-quality observations, not correctness defects in the audited paths.
