## AREA WN-07 — Bridge playlists, import/export, tags, duplicates, local files — ROLE A

### 1. Scope reviewed

**Primary file / ranges read (all lines physically read, not skimmed):**

- `core/api.py` L2362–2750 — `import_external_playlist` (2362), `export_playlist` (2416), `create_playlist` (2498), `delete_playlist` (2504), `get_playlists` (2513), `add_to_playlist` (2517), `get_track_info` (2532), `get_playlist_tracks` (2545), `get_yt_playlist_tracks` (2611), `toggle_favorite` (2615), `_auto_save_favorite` (2640), `get_favorite_tracks` (2727)
- `core/api.py` L3399–3479 — `select_avatar` (3399), `create_local_playlist` (3420), `open_local_file` (3436), `_store_artist_binding` (3461)
- `core/api.py` L3876–4024 — `find_duplicate_tracks` (3876), `delete_duplicate_track` (3884), `update_track_tags` (3910), `choose_cover_image` (4002)
- `core/api.py` L70–230 (support code used by the above): `_COVER_MIME_BY_EXT` / `_COVER_EXT_BY_MIME` (78–90), `_ssrf_cache*` (99–158), `_is_ssrf_safe_url` (161), `_extract_first_url` (201); `core/api.py` L1161–1193 `_enrich_track_lufs`; `core/api.py` L1–24 (imports)

**Callees traced into other areas (read; defects attributed to their owner, see §2):**

- `core/database.py` — schema L207–400 (`tracks.file_path TEXT UNIQUE` L219, `playlist_tracks` L260–270, `PRAGMA foreign_keys=ON` L191, dup-cleanup migration comment L385–395), `delete_track` L1484, `update_track_metadata` L1516, `create_playlist`/`create_playlist_ex` L1862–1890, `_cleanup_duplicate_empty_system_playlists` L1892, `get_playlists` L1931, `add_to_playlist` L1950, `add_tracks_to_playlist` L1972, `get_playlist_tracks` L2004, `delete_playlist` L2018, `_remove_exact_duplicate_playlist_entries` L968, `add_track` L1054, `toggle_favorite` L1248, `ensure_track_exists` L1260
- `services/playlist_import_service.py` — `resolve` L39–58, `_resolve_youtube` L60, `_resolve_soundcloud` L126, `_resolve_local_file` L219–345 (owner: **WN-24**)
- `services/smart_playlists.py` (full file, 177 L; owner: **WN-24**)
- `services/audio_fingerprint_service.py` — `compute_file_fingerprint` L26–61, `find_duplicates` L63–113, `delete_duplicate_track` L115–134 (owner: **WN-25**)
- `utils/tag_parser.py` — `parse_tags` L32–118, `write_tags` L237–397 (owner: **WN-27**)
- `utils/file_scanner.py` — `scan_single_file` L52, `_import_file` L111–155 (owner: **WN-27**)
- `core/offline.py` L35–73 `available_track(s)`; `core/app.py` L110–145 (wiring: `cache`, `scanner`, `playlist_importer`, `audio_fingerprint`)
- `core/downloader.py` — `_SUPPORTED_SOURCES` L27, `queue_download` L356–410, `_fetch_from_provider` L629–662, `download_dir` L789, `mark_track_downloaded` L819
- `services/youtube_service.py::get_playlist_tracks` L703–762 (limit honoured, `seen_ids` de-dup)
- `ui/web_new_v2/js/library.js` L100–134, L175–234, L285–318, L460–529; `js/profile.js` L166–181; `js/player.js` L953–1065; `js/utils.js` L840–870; `js/settings.js` L3260–3346; `js/home.js` L234–238, L370–409; `js/library-view.js` L37–52 — read to establish the **bridge contract** each call site depends on
- `tests/conftest.py` L60–176, `tests/test_api_f1_audit.py`, `tests/test_auto_save_favorites.py`, `tests/test_db_core_fixes_f2.py` (existing coverage, to avoid duplicate reporting)
- `.venv_win/Lib/site-packages/webview/__init__.py` L65–67, `webview/window.py` L502–530, `webview/platforms/winforms.py` L718–772 — to pin the **real** `create_file_dialog` return contract; `.venv_win/Lib/site-packages/mutagen/id3/_file.py` L224–275 — to pin mutagen's write semantics

**Verification harnesses run** (scratch scripts under `%TEMP%\opencode\`, nothing in the repo was modified):
`wn07_verify.py` (playlist-name reuse, duplicate membership, cascade delete, empty name, UNIQUE constraints), `wn07_verify2.py` (SQLite `LOWER()` ASCII-only, re-import duplication, failed import into a pre-existing playlist, m3u8 line splitting), `wn07_verify3.py` (mutagen write semantics + fingerprint change after tagging), `wn07_verify4.py` (real `AppApi.export_playlist` path validation / escaping / default dir / name sanitisation), `wn07_verify5.py` (SSRF gate, `get_playlist_tracks` limit, empty playlist name), `wn07_verify6.py` + `wn07_verify7.py` (`update_track_tags` clearing semantics, non-audio file, arbitrary cover bytes).

---

### 2. Findings

#### F-WN-07-1  [P1] — Re-importing (or re-creating) a playlist with an existing name silently duplicates every track

- **File:** `core/api.py:2382-2396` (import loop) + `core/api.py:3420-3434` (`create_local_playlist`), root cause in `core/database.py:1867-1890` (`create_playlist_ex`)
- **Confirmed:** yes
- **Description:** `create_playlist_ex` **reuses** an existing playlist whose name matches (`SELECT id FROM playlists WHERE LOWER(name) = LOWER(?) LIMIT 1`) and reports `created=False`. Both callers then *append* to it without de-duplicating: `import_external_playlist` inserts every resolved track again, and `create_local_playlist` inserts every local track again. The result is a playlist that holds each track twice, with `get_playlists().track_count` reporting double the real number.
- **Cause:** the "same name ⇒ same playlist" rule (a deliberate feature: system playlists must not be duplicated) is combined with a *blind append* on the caller's side. There is no `UNIQUE(playlist_id, track_id)` on `playlist_tracks` and no existence check before `add_to_playlist`.
- **Trigger conditions:** (a) import the same playlist URL twice — 100 % reproducible; (b) import a playlist whose resolved title collides with any existing playlist of the user; (c) press the "create playlist from local tracks" button on the Profile page (`profile.js:177-181`, `create_local_playlist('Локальные')`) a second time — the existing "Локальные" playlist is reused and every local track is appended again.
- **User impact:** the playlist silently doubles (or triples) on every re-import; the sidebar count (`track_count`) is wrong; the DB accumulates unbounded duplicate membership rows.
- **Evidence:**
  ```python
  # core/api.py:2382-2396
  playlist_name = str(name or "").strip() or resolved_name or f"Imported Playlist ({int(time.time())})"
  playlist_id, created = self._core.db.create_playlist_ex(playlist_name, f"Imported from {url}")
  added_count = 0
  for track in tracks:
      ...
      track_id = self._core.db.ensure_track_exists(track)
      if not track_id or not self._core.db.add_to_playlist(playlist_id, track_id):
          raise RuntimeError("Не удалось добавить все треки в локальный плейлист")
      added_count += 1
  ```
  ```python
  # core/database.py:1884-1887
  cursor.execute("SELECT id FROM playlists WHERE LOWER(name) = LOWER(?) LIMIT 1", (clean_name,))
  row = cursor.fetchone()
  if row:
      return row["id"], False
  ```
- **Reproduction / verification:** `wn07_verify2.py` reproduces the bridge logic verbatim against the real `core/database.py`:
  ```
  import #1 -> playlist_id=5 created=True  added=2
  import #2 -> playlist_id=5 created=False added=2
  membership rows now: 4
    {'id': 1, 'playlist_id': 5, 'track_id': 1, 'title': 'Song A'}
    {'id': 2, 'playlist_id': 5, 'track_id': 2, 'title': 'Song B'}
    {'id': 3, 'playlist_id': 5, 'track_id': 1, 'title': 'Song A'}
    {'id': 4, 'playlist_id': 5, 'track_id': 2, 'title': 'Song B'}
  get_playlists() track_count for that playlist = 4
  ```
- **Suggested fix:** make the import *replace* or *merge* explicitly: when `created is False`, either clear the playlist's membership first, or insert only tracks that are not already members (and report `skipped_count`). Give `create_local_playlist` the same treatment (or a distinct "refresh" semantic).
- **Fix side effects:** clearing a reused playlist would destroy tracks the user added by hand under the same name — merging (skip existing members) is the safer default and must be surfaced in the UI ("N добавлено, M уже было").
- **Discovered by:** A

---

#### F-WN-07-2  [P2] — `add_to_playlist` never de-duplicates: a playlist can hold the same track N times

- **File:** `core/api.py:2517-2530`; `core/database.py:1950-1970` (`add_to_playlist`), `core/database.py:260-270` (`playlist_tracks` schema)
- **Confirmed:** yes
- **Description:** `db.add_to_playlist` is an unconditional `INSERT INTO playlist_tracks (...)`; the table has **no** `UNIQUE(playlist_id, track_id)` constraint (only two plain indexes, `idx_playlist_tracks_pid` / `idx_playlist_tracks_tid`). Adding the same track twice therefore creates two membership rows for the same `(playlist, track)` pair.
- **Cause:** the uniqueness invariant exists only as a *post-hoc cleanup migration* (`core/database.py:968-983` `_remove_exact_duplicate_playlist_entries`), which proves the duplicates are expected to accumulate but is never run on the write path.
- **Trigger conditions:** any second "add to playlist" for a track already in that playlist — from the context menu (`library.js:867`, `library.js:937`), from a repeated import (F-WN-07-1), or from an external playlist that lists the same song twice.
- **User impact:** `get_playlists()` reports `COUNT(pt.track_id)` as the track count → the sidebar shows double. `get_playlist_tracks` returns the same track repeatedly (the library view filters client-side by `track.id`, but the count shown next to the title — `library.js:517` — and the export do not).
- **Evidence:**
  ```python
  # core/database.py:1962-1965
  cursor.execute(
      "INSERT INTO playlist_tracks (playlist_id, track_id, position) VALUES (?, ?, ?)",
      (playlist_id, track_id, next_pos),
  )
  ```
  ```sql
  -- core/database.py:260-268
  CREATE TABLE IF NOT EXISTS playlist_tracks (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      playlist_id INTEGER NOT NULL,
      track_id INTEGER NOT NULL,
      position INTEGER DEFAULT 0,
      added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY (playlist_id) REFERENCES playlists(id) ON DELETE CASCADE,
      FOREIGN KEY (track_id) REFERENCES tracks(id) ON DELETE CASCADE
  )
  ```
- **Reproduction / verification:** `wn07_verify.py` / `wn07_verify5.py`:
  ```
  add #1 -> True
  add #2 -> True
  playlist_tracks rows for playlist 1: 2 -> [{'id': 1, ... 'track_id': 1, 'position': 1},
                                            {'id': 2, ... 'track_id': 1, 'position': 2}]
  get_playlists() track_count for id=1 name='Локальные': 2
  ```
  and `PRAGMA index_list('playlist_tracks')` → `['idx_playlist_tracks_tid', 'idx_playlist_tracks_pid']` (no unique index).
- **Suggested fix:** add `UNIQUE(playlist_id, track_id)` (with a migration that first collapses existing duplicates) or make `add_to_playlist` an `INSERT … WHERE NOT EXISTS` / `INSERT OR IGNORE` and return a "already present" signal.
- **Fix side effects:** the schema change needs a data migration on existing user DBs (the helper at `core/database.py:968` already does the collapsing SQL and can be reused); callers that use the boolean return value must distinguish "added" from "already there".
- **Discovered by:** A

---

#### F-WN-07-3  [P2] — Playlist-name matching is case-SENSITIVE for non-ASCII names (SQLite `LOWER()` is ASCII-only)

- **File:** `core/database.py:1884` (`create_playlist_ex`), also `core/database.py:1910` (`_cleanup_duplicate_empty_system_playlists` uses an exact-match `name IN (...)`)
- **Confirmed:** yes
- **Description:** the documented rule is "if a playlist with the same name already exists (especially system names), reuse it", implemented as `WHERE LOWER(name) = LOWER(?)`. SQLite's built-in `LOWER()` only folds ASCII A–Z; Cyrillic (and every other non-ASCII letter) is left untouched. The app's entire UI is Russian, so most playlist names are Cyrillic → the case-insensitive reuse silently does not apply to them.
- **Cause:** reliance on SQLite's ASCII-only `LOWER()` instead of a Unicode-aware comparison (e.g. `name = ? COLLATE NOCASE` is also ASCII-only in SQLite; a Python-side `casefold()` comparison or a `unicodedata`-aware normalisation is needed).
- **Trigger conditions:** two playlists whose names differ only in Cyrillic case ("Локальные" / "локальные"), or the same playlist re-imported under a differently-cased title.
- **User impact:** inconsistent behaviour — "My Mix"/"my mix" collapse into one playlist while "Мой Микс"/"мой микс" stay two; the system-playlist de-duplication logic (`_cleanup_duplicate_empty_system_playlists`) can no longer clean up case-variant copies of "Локальные".
- **Evidence:**
  ```python
  # core/database.py:1883-1884
  # If playlist with same name already exists (especially system names), reuse it
  cursor.execute("SELECT id FROM playlists WHERE LOWER(name) = LOWER(?) LIMIT 1", (clean_name,))
  ```
- **Reproduction / verification:** `wn07_verify2.py`:
  ```
  LOWER('Локальные') = Локальные
  LOWER('локальные') = локальные
  equal? 0
  cyrillic: id=1/2 created=True/True -> SAME=False      <-- two playlists
  ascii   : id=3/3 created=True/False -> SAME=True      <-- one playlist
  identical cyrillic: id=4/4 created=True/False -> SAME=True
  ```
- **Suggested fix:** compare in Python with `str.casefold()` after fetching candidates (or store a normalised `name_key` column, e.g. `unicodedata.normalize('NFKC', name).casefold()`, and index it).
- **Fix side effects:** existing duplicate playlists that differ only by case would start collapsing into one — a migration must pick a survivor and merge membership, or the change must apply only to new rows.
- **Discovered by:** A

---

#### F-WN-07-4  [P2] — `update_track_tags` cannot clear album / genre / year: the old value is silently substituted

- **File:** `core/api.py:3918-3929`; `core/database.py:1535-1548` (`update_track_metadata`, `COALESCE`); `utils/tag_parser.py:286-288, 314-315, 338-339, 358-360` (owner: **WN-27** for the writer half)
- **Confirmed:** yes
- **Description:** the bridge computes the new values as `tags.get("album") or track.get("album") or ""`. An **empty string** from the UI (the user cleared the field) is falsy, so the *old* value is substituted and written back. The same pattern applies to `genre`. `year` is handled differently: an empty value yields `year = None`, and `write_tags` then simply does not write a year frame — leaving the previous `TDRC` in the file — while `update_track_metadata` uses `COALESCE(NULL, year)`, leaving the old year in the DB. Net effect: **no tag can ever be emptied**.
- **Cause:** "absent" and "explicitly cleared" are conflated; `None` (absent) and `""` (cleared) are not distinguished.
- **Trigger conditions:** the user clears the Album, Genre or Year field in the tag editor and saves.
- **User impact:** the field silently snaps back to the old value in the file and in the library — the editor looks broken; the user cannot remove a wrong album/genre/year.
- **Evidence:**
  ```python
  # core/api.py:3918-3929
  title  = (tags.get("title")  or track.get("title")  or "").strip()
  artist = (tags.get("artist") or track.get("artist") or "").strip()
  album  = (tags.get("album")  or track.get("album")  or "").strip()
  genre  = (tags.get("genre")  or track.get("genre")  or "").strip()
  raw_year = tags.get("year")
  year = None
  if raw_year is not None and str(raw_year).strip():
      ...
  ```
  ```python
  # core/database.py:1539-1542
  album = COALESCE(?, album),
  genre = COALESCE(?, genre),
  year  = COALESCE(?, year),
  ```
- **Reproduction / verification:** `wn07_verify6.py` (bridge) and `wn07_verify7.py` (file):
  ```
  # bridge: update_track_tags(tid, {"title": "New Title", "artist": "New Artist",
  #                                 "album": "", "genre": "", "year": ""})
  -> True None
  DB now: title='New Title' artist='New Artist' album='Old Album' genre='Old Genre' year=1999
  # file: write_tags(..., album="", genre="", year=None)
  file tags: {'TIT2': 'X', 'TPE1': 'Y', 'TDRC': '1999'}      <-- TALB/TCON dropped, TDRC kept
  ```
- **Suggested fix:** treat a **present** key with an empty value as "clear": use `tags["album"]` (KeyError ⇒ absent) rather than `tags.get("album") or …`; pass a sentinel for "no year" so the writer deletes the frame and the DB writes `NULL` instead of `COALESCE`-ing the old value.
- **Fix side effects:** the DB writer uses `COALESCE` precisely so a partial update does not wipe fields; a "clear" sentinel needs a third state (absent / set / clear) through `update_track_metadata`, and the mutagen writer must actively delete the frame (`del tags['TDRC']`).
- **Discovered by:** A

---

#### F-WN-07-5  [P2] — The m3u8 export is not escaped: a newline in a title / artist / playlist name corrupts the exported file

- **File:** `core/api.py:2452-2484` (line building + write)
- **Confirmed:** yes
- **Description:** the exported lines are built by raw string interpolation and joined with `"\n"`. No character escaping is applied to the playlist name, the artist or the title. A newline inside any of them splits one logical line into two physical lines, and the *second* half is parsed by every M3U reader as a **path entry**.
- **Cause:** M3U is a line-oriented format; the writer assumes the metadata never contains a line break. The metadata is user-editable (`update_track_tags` writes arbitrary strings into the DB) and provider-supplied.
- **Trigger conditions:** a title/artist/playlist name containing `\n` or `\r`. Reachable via the tag editor, or via a provider whose title contains a newline.
- **User impact:** the exported `.m3u8` is structurally broken — the file gains a bogus relative path entry ("Title") that most players try to open, and the intended entry after it is mis-associed with the wrong title. The file also uses raw backslash Windows paths, which several non-Windows players cannot resolve.
- **Evidence:**
  ```python
  # core/api.py:2452, 2474-2475
  m3u_lines = ["#EXTM3U", f"#PLAYLIST:{pl_name}"]
  ...
  m3u_lines.append(f"#EXTINF:{duration},{artist} - {title}")
  m3u_lines.append(target_uri)
  ```
  ```python
  # core/api.py:2483-2484
  with open(out_file, "w", encoding="utf-8") as f:
      f.write("\n".join(m3u_lines) + "\n")
  ```
- **Reproduction / verification:** `wn07_verify4.py` (real `AppApi.export_playlist`):
  ```
  --- file content (title = "Bad\nTitle", artist = "A, B") ---
  |#EXTM3U
  |#PLAYLIST:Мой плейлист
  |#EXTINF:180,A, B - Bad
  |Title                       <-- parsed as a PATH entry by every M3U reader
  |C:\Users\...\song.mp3
  ```
- **Suggested fix:** sanitise metadata before writing (replace CR/LF with a space, strip control characters), and consider quoting/escaping per the extended M3U conventions; also emit `file:///C:/…` URIs with forward slashes for portability.
- **Fix side effects:** sanitising changes the exported metadata for tracks whose title legitimately contains a newline (rare); a shared sanitiser should be reused by the tag editor so the DB and the file agree.
- **Discovered by:** A

---

#### F-WN-07-6  [P2] — `update_track_tags` embeds an arbitrary client-supplied file as the cover, with no size or type limit

- **File:** `core/api.py:3936-3957` (read + cache the cover), `core/api.py:4007` (`choose_cover_image` offers "Все файлы (*.*)")
- **Confirmed:** yes
- **Description:** `tags["cover_path"]` is taken verbatim from the JS payload, opened and **read entirely into memory** (`cf.read()`, no size cap), then written to `~/.nedotify/covers/<track_id>.<ext>` — a directory the loopback proxy serves (`core/proxy.py:118` `COVER_EXTENSIONS`, `core/proxy.py:153` `os.path.join(nedotify, 'covers')`). The extension is derived from the *source* file's extension via `_COVER_MIME_BY_EXT`, and any unknown extension silently becomes `image/jpeg` → `.jpg`.
- **Cause:** the cover path is treated as trusted UI output, while it is in fact a free-form string on a bridge method that any script running in the WebView can call.
- **Trigger conditions:** `update_track_tags(track_id, {"cover_path": "<any path>"})`. The bundled picker allows it explicitly ("Все файлы (*.*)").
- **User impact:** (a) a large file is read fully into RAM → memory spike / app stall; (b) the raw bytes of an arbitrary local file are copied into a proxy-served directory under a `.jpg` name and become retrievable through `http://127.0.0.1:<port>/api/cover` (loopback-only bind, so the exposure is to other local processes, not the network); (c) the file is then embedded into the user's audio file, growing it without bound.
- **Evidence:**
  ```python
  # core/api.py:3936-3947
  new_cover_path = tags.get("cover_path") or tags.get("cover_file")
  if new_cover_path and os.path.exists(new_cover_path):
      try:
          with open(new_cover_path, "rb") as cf:
              cover_bytes = cf.read()
          src_ext = os.path.splitext(new_cover_path)[1].lower()
          cover_mime = _COVER_MIME_BY_EXT.get(src_ext, "image/jpeg")
          cover_ext = _COVER_EXT_BY_MIME.get(cover_mime, ".jpg")
  ```
  ```python
  # core/api.py:4007
  file_types = ('Изображения (*.jpg;*.jpeg;*.png;*.webp)', 'Все файлы (*.*)')
  ```
- **Reproduction / verification:** `wn07_verify6.py` — a 600-byte `payload.bin` containing `SECRETSECRETSECR` was accepted and written as `~/.nedotify/covers/1.jpg`:
  ```
  -> True None
  covers dir: ...\home\.nedotify\covers
   1.jpg: 600 bytes, head=b'SECRETSECRETSECR'
  ```
- **Suggested fix:** whitelist the cover extensions (`_COVER_MIME_BY_EXT` keys only), cap the file size (e.g. 10 MB) before reading, and validate the magic bytes of the image rather than trusting the extension.
- **Fix side effects:** users who currently "work around" the picker by passing a `.gif`/`.bmp` would be rejected; the whitelist already contains `.gif`, so only exotic formats are affected.
- **Discovered by:** A

---

#### F-WN-07-7  [P2] — `delete_duplicate_track` is a hard delete: the duplicate's listening history and playlist memberships are CASCADE-deleted with no merge and no warning

- **File:** `core/api.py:3884-3908`; `core/database.py:1484-1489` (`delete_track`), `core/database.py:191` (`PRAGMA foreign_keys=ON`), `core/database.py:260-283` (FK `ON DELETE CASCADE` on `playlist_tracks` and `history`); callee `services/audio_fingerprint_service.py:115-134` (owner: **WN-25**)
- **Confirmed:** yes
- **Description:** "delete duplicate" removes the *whole track row*. With foreign keys enabled, that cascades to `playlist_tracks` (the track leaves every playlist) and to `history` (all listening history for that track is destroyed). The favourite flag, play count and `last_played` of that row die with it. There is no merge step: the surviving copy keeps only *its own* history/favourite, so the user's play statistics for the song are split across two rows and one half is deleted.
- **Cause:** the bridge reuses a destructive primitive where the feature semantically requires a *merge* (re-point history / playlist entries / favourite at the survivor). The repository itself documents this exact hazard at `core/database.py:385-395`:
  > *"the old block DELETed every track row … and let ON DELETE CASCADE take the rows' history, playlist entries, play counts, favourite flags and file references with it - silently (the block logged at DEBUG) and irreversibly (the desktop has no backup feature). The replacement merges instead of deleting."*
  The user-facing duplicate remover reintroduces the very pattern the migration was written to eliminate.
- **Trigger conditions:** any use of Settings → "Duplicate finder" → "Удалить" (the UI always passes `delete_file=true`, `ui/web_new_v2/js/settings.js:3331`). The confirmation modal only says *"Удалить дубликат из медиатеки и с диска?"* and mentions neither history nor playlists.
- **User impact:** the deleted copy vanishes from every playlist it was in and its listening history is gone; if the copy the user deleted was the favourite one, the song leaves "Любимые" with no trace.
- **Evidence:**
  ```python
  # core/api.py:3887-3889
  track = self._core.db.get_track(track_id)
  file_path = (track or {}).get("file_path")
  res = self._core.audio_fingerprint.delete_duplicate_track(self._core.db, track_id, delete_file=delete_file)
  ```
  ```python
  # core/database.py:1484-1489
  def delete_track(self, track_id: int) -> bool:
      with self._write_lock:
          with self.conn:
              cursor = self.conn.cursor()
              cursor.execute("DELETE FROM tracks WHERE id = ?", (track_id,))
              return cursor.rowcount > 0
  ```
- **Reproduction / verification:** `wn07_verify.py`:
  ```
  before: playlist_tracks=2 history=2
  after : playlist_tracks=0 history=0
  ```
  (The `playlist_tracks`/`history` cascade is driven by the FK definitions at `core/database.py:266-267, 280` plus `PRAGMA foreign_keys=ON` at `core/database.py:191`.)
- **Suggested fix:** implement the duplicate removal as a merge — move the duplicate's `history` rows, `playlist_tracks` rows (de-duplicating against the survivor) and its `is_favorite` / `play_count` onto the survivor, then delete the duplicate row (and only then optionally the file). Extend the modal text accordingly.
- **Fix side effects:** merging inflates the survivor's play count/history; the surviving copy may be the *worse* metadata (untagged) — the merge should prefer the richer metadata. The existing merge helpers in `core/database.py` (L740-1000) are a usable template but they were written for a startup migration, not for a user action.
- **Discovered by:** A

---

#### F-WN-07-8  [P2] — `open_local_file` returns a boolean while the UI expects an object: a successful import is reported to the user as a failure

- **File:** `core/api.py:3436-3459` (bridge) vs `ui/web_new_v2/js/library.js:110-131` (consumer); `utils/file_scanner.py:52-56, 111-116` (owner: **WN-27** for the "already imported" behaviour)
- **Confirmed:** yes
- **Description:** the bridge returns `True`/`False`. The consumer tests `res.success || res.count > 0` and `res.cancelled` — all `undefined` on a boolean — so it always falls into the final `else` branch and shows the **warning** toast *"Не удалось импортировать файлы"*, even on a fully successful import. The `res.cancelled` branch can never be taken, so cancelling the dialog produces the same "failure" message.
- **Cause:** a bridge/UI contract mismatch: the bridge method returns a bare boolean while the JavaScript was written against an object shape.
- **Trigger conditions:** any use of Library → "Import local files". Additionally, when the selected file is **already in the library**, `scan_single_file` → `_import_file` returns `None` (`utils/file_scanner.py:112-116`), so `imported` is empty, the bridge returns `False` and the file is **not played** — the user gets a failure toast and silence.
- **User impact:** a successful import is announced as a failure; cancelling is announced as a failure; re-opening a file already in the library does nothing at all (no playback, no explanation).
- **Evidence:**
  ```python
  # core/api.py:3443-3459
  res = self._window.create_file_dialog(dialog_type, allow_multiple=True, file_types=file_types)
  if not res:
      return False
  imported = []
  for file_path in res:
      meta = self._core.scanner.scan_single_file(file_path)
      if meta:
          imported.append(meta)
  if imported:
      self._emit("library_updated", True)
      self.play_track(imported[0], track_list=imported, index=0)
      return True
  ...
  return False
  ```
  ```javascript
  // ui/web_new_v2/js/library.js:114-126
  if (res && (res.success || res.count > 0)) { ... }        // undefined on a boolean
  else if (res && res.cancelled) { /* User closed the dialog — stay silent. */ }
  else { showToast(res?.error || 'Не удалось импортировать файлы', 'warning'); }
  ```
- **Reproduction / verification:** static contract analysis of the two sides (bridge returns the Python `bool`; `true.success` is `undefined`, `true.count > 0` is `false`). The pywebview side is *not* the cause: `webview/platforms/winforms.py:747` returns `tuple(dialog.FileNames)` for `OPEN_DIALOG` (and `None` on cancel), so `res[0]`/`for … in res` in `select_avatar`/`choose_cover_image`/`open_local_file` are correct.
- **Suggested fix:** make the bridge return a dict (`{"success": bool, "cancelled": bool, "count": int, "error": str|None}`) — or make the JS handle the boolean. Also report "already in the library" distinctly instead of `False`.
- **Fix side effects:** the JS also has a second consumer path (`res.count` fallback) — changing the shape requires updating `library.js`; the bridge/UI contract fix belongs to **WN-32** on the JS side.
- **Discovered by:** A

---

#### F-WN-07-9  [P2] — A failed import into a pre-existing playlist leaves the partially imported tracks behind

- **File:** `core/api.py:2405-2414` (rollback), `core/api.py:2385-2387` (`created` flag)
- **Confirmed:** yes
- **Description:** the `except` branch rolls back **only** a playlist this import created (`if playlist_id is not None and created:`). When the import reused an existing playlist of the same name (`created is False`), the tracks already inserted before the failure stay in it. The UI reports "import failed" while the playlist is in fact half-imported.
- **Cause:** the rollback strategy is expressed as "delete the playlist", which is only valid for a playlist the import owns. There is no "undo the rows I added" path for the reused case.
- **Trigger conditions:** an import whose resolved name collides with an existing playlist **and** which fails part-way (a provider hiccup, a track that cannot be resolved, a DB error). The failure is not hypothetical — `db.add_to_playlist` returns `False` on any exception (`core/database.py:1968-1970`) and the import raises on it (`core/api.py:2394-2395`).
- **User impact:** the user's playlist silently gains a random subset of the imported tracks while the UI says the import failed; re-running the import then duplicates that subset again (see F-WN-07-1).
- **Evidence:**
  ```python
  # core/api.py:2405-2414
  except Exception as exc:
      # Roll back only a playlist this import created; a pre-existing one
      # with the same name must never be deleted.
      if playlist_id is not None and created:
          try:
              self._core.db.delete_playlist(playlist_id)
          except Exception:
              logger.exception("Failed to clean up incomplete imported playlist")
      logger.error("Playlist import failed: %s", exc)
      return {"success": False, "error": str(exc) or "Не удалось импортировать плейлист"}
  ```
- **Reproduction / verification:** `wn07_verify2.py` §C reproduces the branch logic; the existing test `tests/test_api_f1_audit.py:287-301` (`test_import_rollback_keeps_preexisting_playlist`) pins only that the playlist survives — it does not assert that the partially added rows are removed, which is exactly the gap.
- **Suggested fix:** track the ids inserted by *this* import and delete exactly those `playlist_tracks` rows in the failure path, for both the created and the reused case.
- **Fix side effects:** deleting rows that were already present before the import (same track, added earlier by the user) must be avoided — the fix needs the *inserted* row ids, not the track ids.
- **Discovered by:** A

---

#### F-WN-07-10  [P2] — Tagging a track silently removes it from duplicate detection

- **File:** `core/api.py:3910-3996` (`update_track_tags` → `write_tags`); `utils/tag_parser.py:237-397` (owner: **WN-27**); `services/audio_fingerprint_service.py:26-61` (`compute_file_fingerprint`, owner: **WN-25**)
- **Confirmed:** yes
- **Description:** the duplicate fingerprint is a hash of the **raw file bytes** (head + middle + tail samples) combined with the file size. Writing tags rewrites the file (mutagen rewrites the ID3 header), so both the hash *and* the size change. Tagging one copy of a duplicated song therefore makes the two copies stop matching, and the "Duplicate finder" silently stops reporting them. Tagging the *other* copy with identical tags would make them match again — the result depends on metadata, not on audio content.
- **Cause:** the fingerprint is not metadata-independent (root cause owned by **WN-25**, `services/audio_fingerprint_service.py:26-61`), and the tag writer mutates the file in place (owner **WN-27**). The bridge exposes the combination: `update_track_tags` invalidates the fingerprint that `find_duplicate_tracks` depends on.
- **Trigger conditions:** any tag edit on a file that has a duplicate elsewhere; also any tag edit on a *downloaded* track (see F-WN-07-11, which the finder does not scan at all).
- **User impact:** the user edits the tags of one copy, then the duplicate finder reports "no duplicates found" for a pair that is still there — the user either misses the duplicate or, worse, deletes the wrong file later.
- **Evidence:**
  ```python
  # services/audio_fingerprint_service.py:52-58
  fingerprint_hash = md5_hash.hexdigest()
  return {
      "hash": fingerprint_hash,
      "file_size": file_size,
      "full_hash": file_size <= sample_bytes * 3,
      "signature": f"{fingerprint_hash}_{file_size}"
  }
  ```
  ```python
  # core/api.py:3966-3976
  from utils.tag_parser import write_tags
  write_tags(file_path, title=title, artist=artist, album=album, genre=genre,
             year=year, cover_bytes=cover_bytes, cover_mime=cover_mime)
  ```
- **Reproduction / verification:** `wn07_verify3.py` — two byte-identical copies, then one is tagged:
  ```
  before tagging:
    copy1: ('f44107be163fb17e0b332ad2dd709797_1060', 1060)
    copy2: ('f44107be163fb17e0b332ad2dd709797_1060', 1060)
    same signature -> True
  after tagging copy1:
    copy1: ('f4d8db8cd24e1c88a722bc41c5c7be8c_1060', 1060)
    copy2: ('f44107be163fb17e0b332ad2dd709797_1060', 1060)
    same signature -> False
  ```
- **Suggested fix:** compute the fingerprint over the **audio frames only** (skip the ID3/Vorbis metadata region), so tags no longer affect it — that is a **WN-25** change. On the WN-07 side, the tag editor should re-run the fingerprint for the edited track after a successful write.
- **Fix side effects:** skipping metadata changes the fingerprint of every existing file → the duplicate groups are recomputed from scratch on the next scan; the first run after the change will report a different set of groups.
- **Discovered by:** A

---

#### F-WN-07-11  [P2] — The duplicate finder never sees downloaded tracks (only `source = 'local'` rows)

- **File:** `core/api.py:3876-3882` (bridge) → `services/audio_fingerprint_service.py:71` (`db_manager.get_all_tracks(source="local")`); `core/database.py:1278-1282` (`mark_track_downloaded` keeps `source` unchanged) — root cause owner: **WN-25**
- **Confirmed:** yes
- **Description:** `find_duplicates` scans only rows whose `source` is `'local'`. A track downloaded from YouTube/SoundCloud keeps `source='youtube'`/`'soundcloud'` — `mark_track_downloaded` only sets `is_downloaded` and `file_path`. The most common duplicate case (the same song downloaded twice) is therefore invisible to the feature, even though those files are on disk and have a `file_path`.
- **Cause:** the scan filter was written for the "scanned music folder" model and was never widened to "every row that has a `file_path`".
- **Trigger conditions:** any duplicate pair where at least one copy was downloaded rather than imported from a folder.
- **User impact:** the Settings → "Duplicate finder" panel reports "дубликатов не обнаружено" for a library full of duplicated downloads; the user is left with duplicate files consuming disk.
- **Evidence:**
  ```python
  # services/audio_fingerprint_service.py:71
  all_tracks = db_manager.get_all_tracks(source="local")
  ```
  ```python
  # core/database.py:1278-1282
  def mark_track_downloaded(self, track_id: int, file_path: str) -> None:
      ...
      cursor.execute("UPDATE tracks SET is_downloaded = 1, file_path = ? WHERE id = ?", (file_path, track_id))
  ```
- **Reproduction / verification:** static trace — `source` is never rewritten by the download path (`core/downloader.py:819` → `mark_track_downloaded`), while the scanner always writes `source="local"` (`utils/file_scanner.py:134`).
- **Suggested fix:** scan every row that has a non-empty `file_path` (WN-25), regardless of `source`.
- **Fix side effects:** the scan cost grows (each candidate file is read 3×); the UI already groups by group, so no UI change is needed.
- **Discovered by:** A

---

#### F-WN-07-12  [P2] — The tag write mutates the user's audio file in place with no atomic replace; the only backup is a transient TEMP copy that is deleted on success

- **File:** `core/api.py:3962-3976` (bridge call site); `utils/tag_parser.py:264-267` (backup), `utils/tag_parser.py:388-397` (delete/restore) — writer owner: **WN-27**
- **Confirmed:** yes
- **Description:** `write_tags` copies the file to `tempfile.mkstemp()` (the system TEMP dir, typically a *different volume* from the music folder) and then calls mutagen, which **rewrites the file in place**. On success the backup is deleted (`os.remove(backup_path)`), so no user-visible backup survives. On an *exception* the backup is copied back — but a process kill, a power loss, or a hard crash between the `insert_bytes`/`delete_bytes` and the end of the write leaves the audio file shifted or truncated, and the backup is gone or orphaned in TEMP. There is no temp-file + `os.replace()` atomic swap.
- **Cause:** mutagen's `ID3.save()` is an in-place editor by design (`mutagen/id3/_file.py:268-273`: `insert_bytes`/`delete_bytes` then `f.seek(0); f.write(data)`); `write_tags` relies on a copy for rollback rather than on an atomic replace.
- **Trigger conditions:** a tag edit on any local file while the process is killed / the machine loses power / the disk fills up mid-write (in which case the `write` raises *after* the file has already been shifted — the restore path copies the backup back, so that specific case is covered).
- **User impact:** the user's only copy of a song can be destroyed. The app has no backup feature of its own (the repository says so explicitly at `core/database.py:389-390`).
- **Evidence:**
  ```python
  # utils/tag_parser.py:264-267
  backup_fd, backup_path = tempfile.mkstemp(prefix="aura_tag_backup_", suffix=os.path.splitext(filepath)[1])
  os.close(backup_fd)
  shutil.copy2(filepath, backup_path)
  ```
  ```python
  # utils/tag_parser.py:388-397
  if os.path.exists(backup_path):
      os.remove(backup_path)
  return True
  except Exception as e:
      # Atomic rollback on any mutagen write failure
      if os.path.exists(backup_path):
          shutil.copy2(backup_path, filepath)
          os.remove(backup_path)
      raise RuntimeError(f"Ошибка при записи тегов в файл: {e}")
  ```
- **Reproduction / verification:** `wn07_verify3.py` inspected the installed mutagen (1.48.1):
  ```
  uses tempfile/rename/os.replace in ID3.save: False
  writes in place (f.write(data) after insert/delete_bytes): True
  aura_tag_backup_* in TEMP: 0        <-- the backup is removed on success
  ```
  and `mutagen/id3/_file.py:268-275` (`insert_bytes` / `delete_bytes` / `f.write(data)`).
- **Suggested fix:** write to a sibling temp file in the *same directory* and `os.replace()` it over the original (atomic on NTFS), keep the old backup until the replace succeeds, and only then delete it. This is a **WN-27** change in `utils/tag_parser.py`.
- **Fix side effects:** `os.replace` across the same volume is atomic but changes the file inode and loses the original timestamps/ACLs unless re-applied; the copy also doubles the peak disk usage during the write (already true today, because the backup is a full copy).
- **Discovered by:** A

---

#### F-WN-07-13  [P3] — `get_playlist_tracks` ignores the `limit` argument for the local source

- **File:** `core/api.py:2545-2568` (local branch), `core/api.py:2600` (remote branch), `core/database.py:2004-2016` (`db.get_playlist_tracks`, no `LIMIT`)
- **Confirmed:** yes
- **Description:** the `limit` parameter is only forwarded to the remote services (`srv.get_playlist_tracks(playlist_id, limit=limit, …)`). The local branch calls `db.get_playlist_tracks(playlist_id)`, whose SQL has no `LIMIT`, so the *entire* playlist is returned regardless of the requested limit.
- **Cause:** the DB helper has no limit parameter; the bridge only added the limit for the remote code path.
- **Trigger conditions:** opening a playlist with many tracks from the Library view (`library.js:504` calls `get_playlist_tracks(data.id)` — no limit at all).
- **User impact:** the whole playlist is serialised across the bridge in one payload; on top of that, `_enrich_track_lufs` (`core/api.py:1161-1193`) performs **one extra `get_track` query per track** whenever `loudness_lufs` is NULL (i.e. for every track the LUFS scanner has not processed yet) → 120 tracks ⇒ 120 extra queries plus a 120-item JSON payload. The default `limit=50` is therefore a silent no-op for local playlists (not a truncation — the opposite).
- **Evidence:**
  ```python
  # core/api.py:2549-2551
  if source == "local":
      try:
          db_tracks = self._core.db.get_playlist_tracks(playlist_id) or []
  ```
  ```python
  # core/database.py:2004-2016
  def get_playlist_tracks(self, playlist_id: int) -> List[Dict[str, Any]]:
      cursor.execute("""
          SELECT t.*, pt.position, pt.added_at as added_to_playlist_at
          FROM playlist_tracks pt JOIN tracks t ON pt.track_id = t.id
          WHERE pt.playlist_id = ? ORDER BY pt.position ASC
      """, (playlist_id,))
  ```
- **Reproduction / verification:** `wn07_verify5.py`:
  ```
  requested limit=5 -> returned 120 tracks
  ```
- **Suggested fix:** add a `LIMIT`/`OFFSET` to `db.get_playlist_tracks` and honour `limit` in the local branch, or make the UI paginate explicitly; also let `_enrich_track_lufs` read the value that is already in the row (it does — the extra query only happens when the column is NULL, so a single batched query for the missing LUFS values is the fix).
- **Fix side effects:** a hard limit would silently hide tracks unless the UI shows a "show more" affordance; the smart-playlist path already implements pagination (`services/smart_playlists.py:128-177`) and could be used as the model.
- **Discovered by:** A

---

#### F-WN-07-14  [P3] — `export_playlist` ignores its `format` argument, and the default output directory is not the Windows "Music" folder

- **File:** `core/api.py:2416` (signature), `core/api.py:2429-2435` (output directory)
- **Confirmed:** yes
- **Description:** two defects in one method. (a) `format` is accepted but never used — the body always produces an M3U8 file, although the docstring promises "…or specified format". (b) The default output directory is chosen as `~/Music`, then `~/Downloads`, then `~`. On a localised Windows those folders are named "Музыка" / "Загрузки", so **neither** exists and the playlist is silently written to the user's **home directory root**.
- **Cause:** the folder names are hard-coded in English and are probed with `os.path.exists`; there is no use of the Windows known-folder API (`SHGetKnownFolderPath`) or of `USERPROFILE\Music`.
- **Trigger conditions:** any export without an explicit `target_path` on a non-English Windows (the whole UI of this app is Russian).
- **User impact:** the exported `.m3u8` lands in `C:\Users\<user>\` instead of the Music folder — easy to lose, and the success toast shows the path so the user can find it, but the location is unexpected.
- **Evidence:**
  ```python
  # core/api.py:2416
  def export_playlist(self, playlist_id: int, format: str = "m3u8", target_path: str = None) -> dict:
      """Export playlist tracks to standard M3U8 playlist file or specified format."""
  ```
  ```python
  # core/api.py:2429-2435
  music_dir = os.path.expanduser("~/Music")
  if not os.path.exists(music_dir):
      music_dir = os.path.expanduser("~/Downloads")
  if not os.path.exists(music_dir):
      music_dir = os.path.expanduser("~")
  out_file = os.path.join(music_dir, f"{safe_name}.m3u8")
  ```
- **Reproduction / verification:** `wn07_verify4.py` §5/§6:
  ```
  format='pls' -> {'success': True, ...}      written: ['#EXTM3U', '#PLAYLIST:Мой плейлист']
  ~/Music exists? False ; ~/Downloads exists? False
  -> file landed in: ...\home          (home root, not a Music folder)
  ```
- **Suggested fix:** either drop the unused `format` parameter or implement it; resolve the Music folder through the known-folder API (or check both the English and the localised names) and expose the chosen directory in the result.
- **Fix side effects:** changing the default output folder moves where past exports were written; the toast already carries the full path, so users can find the file.
- **Discovered by:** A

---

#### F-WN-07-15  [P3] — `update_track_tags` reports success for a file it cannot tag, and leaves the DB out of sync with the file

- **File:** `core/api.py:3961-3976` (write), `core/api.py:3979-3990` (DB update), `utils/tag_parser.py:372-386` (the unsupported-format fallback)
- **Confirmed:** yes
- **Description:** for an extension mutagen does not handle, `write_tags` falls into the generic branch, `MutagenFile(filepath, easy=True)` returns `None`, nothing is written, and the function returns `True`. The bridge therefore reports success and updates the DB — the library shows the new title while the file on disk is unchanged. The same divergence appears whenever the DB update fails after a successful file write (the file keeps the new tags, the DB keeps the old ones).
- **Cause:** the writer cannot distinguish "wrote the tags" from "there was nothing to write", and the file/DB update order is file-then-DB with no compensation.
- **Trigger conditions:** a track row whose `file_path` points at a non-audio file (possible: `add_track` accepts any `file_path`), or a DB write error after a successful tag write.
- **User impact:** the UI shows metadata that is not in the file; the next folder rescan reverts it (or the user's manual edit to the file is silently ignored by the app).
- **Evidence:**
  ```python
  # utils/tag_parser.py:372-386
  else:
      # Fallback for other formats with EasyID3/EasyMutagen
      audio = MutagenFile(filepath, easy=True)
      if audio is not None:
          ...
          audio.save()
  ```
  (`write_tags` then falls through to `return True` — the "nothing was written" case is not reported.)
  ```python
  # core/api.py:3966-3990
  write_tags(file_path, title=title, artist=artist, ...)
  db_res = self._core.db.update_track_metadata(track_id=track_id, ...)
  if not db_res:
      return {"success": False, "error": "Не удалось обновить запись в базе данных"}
  ```
- **Reproduction / verification:** `wn07_verify6.py`:
  ```
  # a .txt row tagged as if it were an audio file
  -> True None
  file content unchanged: 'hello'
  DB title now: 'Renamed'
  ```
- **Suggested fix:** have `write_tags` return `False` (or raise) when it could not write any tag, and have the bridge report "the file format does not support tags" instead of success; on a DB failure after a successful file write, say so explicitly ("the file was updated, the library record was not").
- **Fix side effects:** callers that currently rely on `write_tags` returning `True` unconditionally would start reporting failures for formats that legitimately have no tag support.
- **Discovered by:** A

---

#### F-WN-07-16  [P3] — The favourite → auto-download path queues a download for sources that have no download provider

- **File:** `core/api.py:2640-2725` (`_auto_save_favorite`), `core/api.py:2722` (`queue_download`); `core/downloader.py:27` (`_SUPPORTED_SOURCES`), `core/downloader.py:631-634` (owner: **WN-13** for the downloader half)
- **Confirmed:** yes
- **Description:** `_auto_save_favorite` queues a download for **every** non-`local` source. `_SUPPORTED_SOURCES` is `{youtube, soundcloud, yandex, spotify, spotify_album}` — `vk`, `itunes`, `lastfm` and anything else are not covered, so the worker fails immediately with *"No download provider for source 'vk'."* and the user gets a failed download entry for a track they merely liked.
- **Cause:** the bridge does not consult the set of sources that actually have a download provider before queueing.
- **Trigger conditions:** `auto_download_favorites` enabled + favouriting a track whose `source` is not in `_SUPPORTED_SOURCES` (VK is a first-class provider in this app).
- **User impact:** a spurious failed download in the download queue / "downloads" view, and a `download_failed` event for a track that the user never asked to download.
- **Evidence:**
  ```python
  # core/api.py:2716-2725
  payload = dict(track_data)
  payload["id"] = track_id
  payload["source"] = source
  payload["source_id"] = str(source_id)
  queued = bool(self._core.downloader.queue_download(track_id, source, str(source_id)))
  ```
  ```python
  # core/downloader.py:631-634
  if source not in _SUPPORTED_SOURCES:
      raise Exception(f"No download provider for source '{source}'.")
  ```
- **Reproduction / verification:** static trace — `_auto_save_favorite` has no source whitelist; `queue_download` accepts any source; the failure is raised in `_fetch_from_provider` and is **not** in `_RETRYABLE_MARKS` (`core/downloader.py:612`), so it fails on the first attempt.
- **Suggested fix:** skip the queue for sources without a download provider (share the `_SUPPORTED_SOURCES` set with the bridge) and still perform the stream-cache step, which is source-agnostic.
- **Fix side effects:** none for supported sources; the auto-download feature would silently stop producing failed rows for VK.
- **Discovered by:** A

---

#### F-WN-07-17  [P3] — `create_playlist` accepts a blank name; `delete_playlist` reports success for a playlist that does not exist and does not protect the system playlists

- **File:** `core/api.py:2498-2502` (`create_playlist`), `core/database.py:1879` (`clean_name = (name or "").strip()`); `core/api.py:2504-2511` (`delete_playlist`), `core/database.py:2018-2026` (`db.delete_playlist`)
- **Confirmed:** yes
- **Description:** three small contract gaps. (a) `create_playlist` performs no validation: a name of `"   "` is stored as an empty playlist name (`name TEXT NOT NULL` accepts `''`). The UI's quick-add field guards against this (`library.js:214-215`), but the bridge does not, and the name may contain control characters or be arbitrarily long. (b) `delete_playlist` returns `{"success": True, "res": False}` when the id does not exist — the caller cannot distinguish "deleted" from "was never there". (c) Nothing prevents deleting the system playlists `'Локальные'` / `'Локальные треки'`, which the UI treats specially (`ui/web_new_v2/js/library-view.js:37` maps the playlist named exactly `Локальные` to the *local collection* view).
- **Cause:** the bridge methods are thin wrappers with no argument validation, and the DB layer stores the name as given.
- **Trigger conditions:** (a) any direct bridge call with a blank/odd name; (b) deleting an already-deleted playlist (double click / stale UI); (c) deleting the "Локальные" playlist from the sidebar.
- **User impact:** unnamed playlists in the sidebar; a misleading success toast on a no-op delete; the "Локальные" collection disappearing from the playlist list (its tracks are **not** lost — verified: `delete_playlist` only removes the membership rows, the `tracks` rows survive).
- **Evidence:**
  ```python
  # core/api.py:2498-2502
  def create_playlist(self, name: str, description: str = ""):
      """Create new user playlist."""
      pid = self._core.db.create_playlist(name, description)
      self._emit("playlists_updated", self.get_playlists())
      return pid
  ```
  ```python
  # core/database.py:1879
  clean_name = (name or "").strip()
  ```
  ```python
  # core/api.py:2507-2509
  res = self._core.db.delete_playlist(int(playlist_id))
  self._emit("playlists_updated", self.get_playlists())
  return {"success": True, "res": res}
  ```
- **Reproduction / verification:** `wn07_verify.py` §5 and `wn07_verify5.py` §6:
  ```
  created id=4 created=True name=''
  create_playlist('   ') -> id=3 stored name=''
  ```
  and `wn07_verify.py` §4 — the tracks survive a playlist delete:
  ```
  delete_playlist -> True
  track row still present: True
  membership rows: 0
  ```
- **Suggested fix:** validate the name in `create_playlist` (non-empty after strip, trimmed length limit, reject control characters) and return `{"success": False, "error": ...}` instead of raising; make `delete_playlist` return `success=False` when `res` is `False`; refuse to delete the reserved system playlist names (or rename them out of the user namespace).
- **Fix side effects:** rejecting blank names changes the behaviour of `create_local_playlist` (which passes the literal `"Локальные"` — fine) and of any script that creates a playlist with an empty name today.
- **Discovered by:** A

---

#### F-WN-07-18  [P3] — The importer's local-file branch is unreachable through the bridge (a documented feature is dead code), and a remote `.m3u8` URL is mis-routed to the local-file parser

- **File:** `core/api.py:2364-2367` (the SSRF gate) vs `services/playlist_import_service.py:39-58` and `services/playlist_import_service.py:219-222` (owner: **WN-24**)
- **Confirmed:** yes
- **Description:** `PlaylistImportService.resolve` documents that it handles "external **and local** playlist formats (YouTube, SoundCloud, M3U/M3U8, JSON, text lists)" and branches to `_resolve_local_file` when the target exists on disk or ends in `.m3u/.m3u8/.json/.txt`. The bridge's SSRF gate rejects anything that is not `http(s)` (verified: a local path and a `file://` URL are both refused with *"Некорректная или небезопасная ссылка"*), so the local-file branch can never be reached from the UI. Conversely, a **remote** `https://host/list.m3u8` passes the SSRF gate but `resolve()` routes it to `_resolve_local_file` (because of the `endswith(".m3u8")` test) and fails with *"Файл плейлиста не найден: https://host/list.m3u8"*.
- **Cause:** the bridge's contract (http/https only) and the service's contract (URL **or** local path) were never reconciled; the service's extension test does not distinguish a URL from a path.
- **Trigger conditions:** the user pastes a direct link to a remote `.m3u8` file → the import fails with a confusing "file not found" message showing the URL. Importing a local `.m3u` file is impossible from the UI.
- **User impact:** a legitimate import path (a hosted `.m3u8` playlist) is broken; the local-file import that the service was written for cannot be reached.
- **Evidence:**
  ```python
  # core/api.py:2364-2367
  url = _extract_first_url(url or "")
  if not url or not _is_ssrf_safe_url(url):
      logger.warning("SSRF block triggered for playlist import URL: %s", url)
      return {"success": False, "error": "Некорректная или небезопасная ссылка"}
  ```
  ```python
  # services/playlist_import_service.py:45-47
  # 1. Local file or M3U/JSON text content
  if os.path.exists(target) or target.endswith((".m3u", ".m3u8", ".json", ".txt")):
      return self._resolve_local_file(target)
  ```
- **Reproduction / verification:** `wn07_verify5.py`:
  ```
  _is_ssrf_safe_url('C:\\Users\\me\\list.m3u8')       = False
  _is_ssrf_safe_url('file:///C:/Users/me/list.m3u8')  = False
  import('C:\\Users\\me\\list.m3u8')      -> {'success': False, 'error': 'Некорректная или небезопасная ссылка'}
  import('file:///C:/Users/me/list.m3u8') -> {'success': False, 'error': 'Некорректная или небезопасная ссылка'}
  importer.resolve() calls: []
  ```
- **Suggested fix:** (a) in `playlist_import_service.resolve` (WN-24), test the URL-ness *before* the extension test, and fetch a remote `.m3u8` over HTTP with the SSRF guard applied; (b) either expose a separate `import_local_playlist(path)` bridge method (with its own path validation) or drop the local-file branch.
- **Fix side effects:** allowing remote `.m3u8` fetches re-opens an SSRF surface — the fetch must go through `_is_ssrf_safe_url` and the proxy's safe-redirect handler.
- **Discovered by:** A

---

### 3. Clean areas

Checked and found **correct** (no finding raised):

- **`export_playlist` target-path validation** (`core/api.py:2436-2450`) — solid. `os.path.realpath` resolves `..` and symlinks/junctions; the extension is whitelisted to `.m3u8`/`.m3u`; the target must live under `os.path.realpath(os.path.expanduser("~"))` (a different drive raises `ValueError` from `commonpath`, which is caught and treated as "outside home"); the parent directory must already exist. Verified empirically: an absolute path outside home, a `..` path, and a disallowed extension are all refused and **no file is created**; a path inside home is accepted. This is the single most security-sensitive method in the area and it holds.
- **Playlist-name → output filename sanitisation** (`core/api.py:2423`) — `"../../etc/passwd"` becomes `etcpasswd.m3u8`; no path separators, no traversal, and an all-symbol name falls back to `playlist_<id>`.
- **Empty playlist export** (`core/api.py:2426-2427`) — a clean, explicit error; no empty file is produced.
- **SSRF gate on import** (`core/api.py:2364-2367`, `_is_ssrf_safe_url` at `core/api.py:161-195`) — rejects non-`http(s)` schemes, loopback/private/link-local/reserved IPs (including the decimal-integer form `2130706433`), and the DNS verdict is memoised with a bounded cache. The bridge applies it **before** the importer is reached (verified: `importer.resolve()` was never called for a rejected URL).
- **pywebview file-dialog contract** — verified against the installed pywebview 5.4: `webview.FileDialog` does not exist, so `webview.OPEN_DIALOG` (= 10) is used; `webview/platforms/winforms.py:747` returns a **tuple** of paths for `OPEN_DIALOG` and `None` on cancel. Therefore `select_avatar` (`res[0]`), `choose_cover_image` (`result[0]`) and `open_local_file` (`for … in res`, `if not res`) all index the result correctly, and the `getattr(webview, 'FileDialog', webview).OPEN` expression never raises (the `getattr` branch is not evaluated when the attribute is absent).
- **`delete_playlist` does not destroy tracks** — verified: only the `playlist_tracks` membership rows and the `playlists` row are deleted; the `tracks` rows survive (`core/database.py:2018-2026`). The FK cascade only removes *membership*, not the library.
- **`db.add_to_playlist` / `db.add_tracks_to_playlist` are transactional** — each runs inside `with self._write_lock: with self.conn:` and returns `False`/`0` on failure instead of raising; `add_tracks_to_playlist` inserts the whole batch in one transaction (`executemany`) so a partial batch is not possible.
- **`toggle_favorite` state machine** — the read-modify-write is serialised by `_write_lock` + the SQLite transaction (`core/database.py:1248-1258`), the bridge returns the **new** state (`is_favorite`), and the auto-save side effect fires only on the transition *to* favourite (`core/api.py:2629-2637`), so un-liking never deletes or downloads anything. A failed auto-download is caught and cannot break the like itself. The contracts are pinned by `tests/test_auto_save_favorites.py`.
- **`_auto_save_favorite` quota accounting** — the scanned directory (`~/.nedotify/downloads`) matches the downloader's actual `download_dir` (`core/downloader.py:789`); a quota of `0` means unlimited; the size scan is exception-safe; the queue call is de-duplicated by the downloader (DB unique row + in-memory check), so a like/un-like/like cycle cannot queue the same track twice.
- **`_auto_save_favorite` skips local tracks and already-downloaded tracks** — verified against the code and pinned by `tests/test_auto_save_favorites.py`.
- **`get_playlist_tracks` remote path** — the limit **is** honoured for YouTube/SoundCloud/Spotify (`youtube_service.py:758`), the callback thread is joined with a bounded `BRIDGE_SYNC_BUDGET` timeout, the `threading.Event` provides the memory barrier for the shared `result` dict, and an error callback takes precedence over a success callback.
- **`find_duplicate_tracks` / `delete_duplicate_track` error paths** — the bridge reports an honest `{"success": False, "partial": True}` when the file survived the delete (the DB row is already gone at that point), and it refreshes the library in both cases so the UI cannot keep showing a row the backend no longer has. This is pinned by `tests/test_api_f1_audit.py:226-270`.
- **`_store_artist_binding`** (`core/api.py:3461-3475`) — takes `_window_op_lock`, copies the settings dict before mutating it, and only stores bindings for `youtube`/`itunes` profiles with an id and a name.
- **`update_track_tags` file-write permission check** — the bridge checks `os.access(file_path, os.W_OK)` and returns a friendly message instead of letting mutagen raise; `write_tags` re-checks and raises `PermissionError`.
- **`get_track_info`** — returns `None` for a missing id and swallows exceptions into `None` rather than raising across the bridge.

---

### 4. Coverage gaps

- **Not executed:** the real `pywebview` GUI was never launched (forbidden by the ground rules), so the *behaviour* of the native dialogs (focus, the actual file list, the WinForms filter string built from `('Image Files (*.jpg;*.png;*.webp)',)`) was validated only against the installed pywebview source, not against a running window. `parse_file_type` was not exercised with the app's own filter strings.
- **Not executed:** the whole `export_playlist` → external-player round trip (no third-party M3U reader was available); the corruption in F-WN-07-5 was demonstrated on the generated bytes, not on a player's reaction.
- **Not executed:** `import_external_playlist` against the live providers (YouTube / SoundCloud) — network calls are out of bounds for this run and `pytest.ini` deselects the `network` marker. The importer's behaviour was established from the source plus a stub importer (`tests/test_api_f1_audit.py` uses the same shape).
- **Not executed:** `update_track_tags` against real-world tag sets (ID3v2.2/v2.3/v2.4, MP4 atoms, Vorbis comments) — only a synthetic ID3 file was exercised. The FLAC/MP4/OGG branches of `utils/tag_parser.py` were read, not run.
- **Not executed:** a real crash-during-tag-write scenario (F-WN-07-12) — the in-place-write conclusion comes from the installed mutagen's source and from the absence of a temp-file/rename in `ID3.save`, not from an induced crash.
- **Not exercised:** `services/smart_playlists.py` was read in full and confirmed to be a *separate* table (`smart_playlists`) with its own bounded pagination, so `delete_playlist` does **not** touch smart playlists — but the bridge method that deletes them (`get_smart_playlist_tracks` and friends) lives outside this area's line ranges and was not reviewed.
- **Not reviewed (out of the assigned ranges, adjacent):** `core/api.py` L2727–2733 (`get_favorite_tracks`, the last lines of WN-06's range), the `downloads`-list and `smart playlist` bridge methods in the L3595–4228 band (WN-10), and `core/api.py` L2750–3195 / L4021–4110 (WN-08).
- **Callee-owned defects deliberately NOT claimed here** (owner named instead, to avoid double reporting): the substring-based provider routing and the remote-`.m3u8` mis-routing in `services/playlist_import_service.py` → **WN-24**; the metadata-sensitive fingerprint and the `source='local'`-only scan in `services/audio_fingerprint_service.py` → **WN-25**; the in-place mutagen write and the unbounded cover read in `utils/tag_parser.py` → **WN-27**; the `source not in _SUPPORTED_SOURCES` failure in `core/downloader.py` → **WN-13**; the "already imported → return `None`" behaviour in `utils/file_scanner.py` → **WN-27**.
- **Locale dependency:** F-WN-07-14 (the `~/Music` fallback) was demonstrated by making `~/Music` and `~/Downloads` absent in a sandbox home; the exact folder names on the target machine ("Музыка"/"Загрузки") were not enumerated from the live system.
