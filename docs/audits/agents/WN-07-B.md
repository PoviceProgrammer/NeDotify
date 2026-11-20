## AREA WN-07 — Bridge playlists, import/export, tags, duplicates, local files — ROLE B

### 1. Scope reviewed

**Files opened (path: line ranges actually read)**

- `core/api.py` — L1–120 (imports, `_COVER_MIME_BY_EXT`/`_COVER_EXT_BY_MIME`), L121–240 (`_is_ssrf_safe_url`, `_extract_first_url`), L1161–1220 (`_enrich_track_lufs`), **L2355–2754** (`import_external_playlist`, `export_playlist`, `create_playlist`, `delete_playlist`, `get_playlists`, `add_to_playlist`, `get_track_info`, `get_playlist_tracks`, `get_yt_playlist_tracks`, `toggle_favorite`, `_auto_save_favorite`, `get_favorite_tracks`), **L3390–3479** (`select_avatar`, `create_local_playlist`, `open_local_file`, `_store_artist_binding`), **L3866–4025** (`find_duplicate_tracks`, `delete_duplicate_track`, `update_track_tags`, `choose_cover_image`, head of `get_storage_details`)
- `core/database.py` — L82–93 (identity constants), L155–205 (`_local`, `_write_lock`, `_get_connection`), L207–388 (schema: `tracks`, `playlists`, `playlist_tracks`, `history`, indexes), L505–634 (`_run_dup_cleanup_migration`), L871–980 (`_merge_track_row_into`, `_remove_exact_duplicate_playlist_entries`), L1040–1169 (`add_track`), L1166–1359 (`get_track`, `get_all_tracks`, `toggle_favorite`, `ensure_track_exists`, `mark_track_downloaded`, `_like_pattern`), L1484–1563 (`delete_track`, `update_track_metadata`), L1855–2034 (playlist CRUD), L2399–2480 (connection lifecycle)
- `core/proxy.py` — L110–289 (`AUDIO_EXTENSIONS`, `_cover_roots`, `_is_inside_roots`, `_resolve_inside_roots`, `_referenced_by_library`, `_safe_stream_local_path`, `_safe_avatar_path`, `_safe_cover_path`)
- `core/api.py` — L4192–4228 (`_smart_playlists` bridge, WN-10, read only for the layering picture)
- `services/audio_fingerprint_service.py` — whole file (134 L)
- `services/playlist_import_service.py` — whole file (345 L)
- `services/smart_playlists.py` — whole file (177 L)
- `services/artist_identity.py` — L1–63
- `utils/tag_parser.py` — L1–60, L211–234, L237–398 (`write_tags`)
- `utils/file_scanner.py` — L1–181
- `utils/cache_manager.py` — L55–135 (`get_cache_size`, `get_storage_details`)
- `ui/web_new_v2/js/utils.js` — L145–172 (`showToast`), L1430–1519 (tag editor modal)
- `ui/web_new_v2/js/settings.js` — L3255–3346 (duplicate modal + groups renderer)
- `ui/web_new_v2/js/library.js` — L165–234, L460–480, L590–610, L860–875
- `ui/web_new_v2/js/library-view.js` — L55–165
- `ui/web_new_v2/js/profile.js` — L160–188
- `ui/web_new_v2/js/player.js` — L1250–1265
- `ui/web_new_v2/js/home.js` — L230–245, L535–545
- `tests/test_dup_cleanup_migration.py` — whole file (665 L)
- `tests/test_auto_save_favorites.py` — whole file (161 L)
- `tests/test_download_integrity.py` — whole file (147 L)
- `tests/test_api_f1_audit.py` — L100–330 (export confinement, duplicate delete, import rollback)
- `tests/test_api_audit_b.py` — L170–250 (cover extension)
- `tests/test_db_integrity.py` — L59–190; `tests/test_db_core_fixes_f2.py` — L167–210, L320–345; `tests/test_catalog_verification.py` — L105–160
- `tests/conftest.py` — whole file (176 L)

**Callees traced into other areas**

| Callee | Owning area | What I attributed there |
|---|---|---|
| `services/playlist_import_service.py::resolve` | WN-24 | Routing bug (remote M3U unreachable) — root cause lives there; reported once here as F-13 with the owner named |
| `services/audio_fingerprint_service.py::delete_duplicate_track` | WN-25 | The file-unlink-before-row-delete ordering — reported as F-3 with the owner named |
| `utils/tag_parser.py::write_tags` | WN-27 | The non-atomic in-place mutagen write and the "writes atomically" docstring — reported as F-7 with the owner named; WN-07 owns the *consequence* (the user's original media file is the target) |
| `core/database.py::_merge_track_row_into` | WN-12 | Correct — used as the contrast in F-2 |
| `core/proxy.py::_safe_stream_local_path` / `_safe_cover_path` | WN-11 | Clean — used as the contrast in F-1 |
| `utils/file_scanner.py::_import_file` | WN-27 | The "already known → None" contract — reported as F-12 with the owner named |

**Runtime verification** (all on throwaway SQLite files and temp dirs; the real `~/.nedotify/` was never opened): 11 probe scripts under `%TEMP%\opencode\`.

---

### 2. Findings

#### F-WN-07-1  [P1] — `update_track_tags` reads an arbitrary client-supplied path and republishes its bytes through the loopback proxy

- **File:** `core/api.py:3936-3957` (+ `core/proxy.py:280-282`, `core/proxy.py:141-167`)
- **Confirmed:** yes
- **Description:** `tags["cover_path"]` is a fully client-controlled absolute path. The bridge opens it, reads it whole, and writes the bytes into `~/.nedotify/covers/<track_id>.<ext>` — a directory the proxy serves. There is no extension check, no root confinement, no size cap, and no proof that the path ever came out of `choose_cover_image()`'s native dialog.
- **Cause:** the bridge treats the "path" as a trusted value because the intended producer is a file dialog. The trust boundary is the JS caller, so any JS that can reach `window.pywebview.api.update_track_tags` can read any file the process can read.
- **Trigger conditions:** any call to `update_track_tags(track_id, {"cover_path": "<arbitrary path>"})`. The UI does exactly this (`ui/web_new_v2/js/utils.js:1474-1488` passes the dialog result through), but nothing enforces that the value *is* a dialog result.
- **User impact:** disclosure of arbitrary local files (any extension — a `.pdf`, a `.txt`, a key file) through `GET /api/cover` on the loopback proxy; the same bytes are also embedded into the user's audio file as an `APIC` frame. Second-order risk: the bridge's other write-side primitives (e.g. `export_playlist(target_path)`) become reachable if any script in the WebView is attacker-controlled.
- **Evidence:**
  ```python
  3936:            new_cover_path = tags.get("cover_path") or tags.get("cover_file")
  3937:            if new_cover_path and os.path.exists(new_cover_path):
  3938:                try:
  3939:                    with open(new_cover_path, "rb") as cf:
  3940:                        cover_bytes = cf.read()
  ...
  3945:                    src_ext = os.path.splitext(new_cover_path)[1].lower()
  3946:                    cover_mime = _COVER_MIME_BY_EXT.get(src_ext, "image/jpeg")
  3947:                    cover_ext = _COVER_EXT_BY_MIME.get(cover_mime, ".jpg")
  ...
  3954:                    cached_cover = os.path.join(covers_dir, f"{track_id}{cover_ext}")
  3955:                    with open(cached_cover, "wb") as f:
  3956:                        f.write(cover_bytes)
  ```
  Note `_COVER_MIME_BY_EXT.get(".pdf", "image/jpeg")` → `image/jpeg` → `.jpg`: a PDF is silently republished as `1.jpg`.
- **Reproduction / verification:** probe `%TEMP%\opencode\wn07_probe7.py`:
  ```
  === PROBE 8: update_track_tags reads an ARBITRARY client-supplied path ===
    result: True None
    DB cover_path: ...\.nedotify\covers\1.jpg
    cached bytes == secret bytes? True
    cached name: 1.jpg  (source was a .pdf!)
    proxy _safe_cover_path(cached) -> '...\.nedotify\covers\1.jpg'
  ```
  i.e. the bytes of `secret.pdf` are copied verbatim into a proxy-servable file.
- **Suggested fix:** make `choose_cover_image()` do the copy itself (into `~/.nedotify/covers/`) and return the *internal* path; then the bridge only accepts a path it minted. Failing that, validate `cover_path` against the allow-list of roots and the image extensions, and cap the size.
- **Fix side effects:** the tag editor would lose the ability to reference a file outside `~/.nedotify` — which is exactly the point; the copy-into-covers step already exists.
- **Discovered by:** B

#### F-WN-07-2  [P1] — Deleting a "duplicate" silently destroys that track's listening history, playlist membership and favourite flag

- **File:** `core/api.py:3884-3908`; `services/audio_fingerprint_service.py:115-134`; `core/database.py:1484-1489` (+ schema `core/database.py:260-270`, `core/database.py:272-281`, `PRAGMA foreign_keys=ON` at `core/database.py:191`)
- **Confirmed:** yes
- **Description:** `delete_duplicate_track` → `AudioFingerprintService.delete_duplicate_track` → `db_manager.delete_track(track_id)` → a bare `DELETE FROM tracks WHERE id = ?`. Because `PRAGMA foreign_keys=ON` and both `playlist_tracks.track_id` and `history.track_id` are `ON DELETE CASCADE`, the row's playlist entries **and its whole listening history** are deleted with it — plus the favourite flag, the play count and `last_played` that live on the track row.
- **Cause:** the runtime duplicate-delete path re-implements "remove a duplicate" as "delete a row", while the codebase already contains the correct algorithm — `_merge_track_row_into` (`core/database.py:871-966`) re-points history rows, playlist entries and download-queue rows at the survivor *before* deleting the duplicate. The migration uses it; the runtime path does not.
- **Trigger conditions:** the user clicks "Удалить" on any row of a duplicate group (the UI always passes `delete_file=true`, `ui/web_new_v2/js/settings.js:3331`).
- **User impact:** silent, irreversible loss of play history (Wrapped/statistics), playlist membership and the favourite flag for the deleted track — with no warning. The confirmation dialog only says "Удалить дубликат из медиатеки и с диска?" (`ui/web_new_v2/js/settings.js:3265`). The surviving twin keeps *its own* history, so the totals silently shrink.
- **Evidence:**
  ```python
  # services/audio_fingerprint_service.py
  121:            track = db_manager.get_track(track_id)
  122:            if track and delete_file:
  ...
  130:            db_manager.delete_track(track_id)
  131:            return True
  ```
  ```python
  # core/database.py
  1484:    def delete_track(self, track_id: int) -> bool:
  1485:        with self._write_lock:
  1486:            with self.conn:
  1487:                cursor = self.conn.cursor()
  1488:                cursor.execute("DELETE FROM tracks WHERE id = ?", (track_id,))
  ```
  Contrast with the correct merge, `core/database.py:926-943`:
  ```python
  931:        cursor.execute("UPDATE history SET track_id = ? WHERE track_id = ?", (survivor_id, duplicate_id))
  ...
  941:        cursor.execute("UPDATE playlist_tracks SET track_id = ? WHERE track_id = ?", (survivor_id, duplicate_id))
  ```
- **Reproduction / verification:** probe `%TEMP%\opencode\wn07_probe4.py`:
  ```
  === PROBE 6: delete_duplicate_track destroys history + playlist membership ===
    before: history= 1  playlist_entries= 1  fav= 1
    after : history= 0  playlist_entries= 0  tracks= 0  file_exists= False
  ```
  The same DB effect from the raw `db.delete_track()` call is in probe `%TEMP%\opencode\wn07_probe1.py` (PROBE 3): `history rows 2 -> 0`, `playlist rows 1 -> 0`.
- **Suggested fix:** route the runtime duplicate-delete through the same merge semantics (re-point `history`, `playlist_tracks`, `download_queue` to the surviving twin of the group, then delete the emptied row); at minimum, warn and offer to keep the entries.
- **Fix side effects:** the merge needs to know the survivor id, so the bridge must pass the group, not just the row id; `playlist_tracks` may gain a duplicate `(playlist, track)` pair, which the migration's `_remove_exact_duplicate_playlist_entries` already knows how to clean.
- **Discovered by:** B

#### F-WN-07-3  [P2] — `delete_duplicate_track(delete_file=True)` unlinks the file without checking whether another row still references it

- **File:** `services/audio_fingerprint_service.py:122-130`; `core/database.py:357-360`; `core/database.py:1278-1282`; `core/api.py:3890-3903`
- **Confirmed:** yes
- **Description:** `os.remove(file_path)` runs **before** `delete_track()`, and nothing checks whether a second `tracks` row points at the same path. On a library created by an older build — which the code itself documents as having no `UNIQUE` on `tracks.file_path` — two rows can share one path, and `mark_track_downloaded` will happily create that state. The result: the file is unlinked and the *other* row is left pointing at a file that no longer exists.
- **Cause:** the delete order is file-first/row-second, and the uniqueness invariant that would make this safe only exists in schemas created after the constraint was added.
- **Trigger conditions:** a pre-`UNIQUE` library in which two track rows share a `file_path`; the duplicate scanner groups them (same content ⇒ same fingerprint), and the user deletes one.
- **User impact:** a broken library entry — the row stays in the library forever, the file is gone, playback fails, and the duplicate scanner can no longer even see it (it skips rows whose file does not exist). Secondary variant: the file is unlinked and *then* `delete_track` fails → the bridge returns `{"success": False, "error": "Не удалось удалить дубликат"}` while the user's music is already deleted and the row still points at nothing.
- **Evidence:**
  ```python
  # services/audio_fingerprint_service.py
  122:            if track and delete_file:
  123:                file_path = track.get("file_path")
  124:                if file_path and os.path.exists(file_path):
  125:                    try:
  126:                        os.remove(file_path)
  127:                    except Exception as fe:
  128:                        logger.warning(f"Could not remove duplicate file {file_path}: {fe}")
  129:
  130:            db_manager.delete_track(track_id)
  ```
  ```python
  # core/database.py:357-360 — the invariant is NOT universal
  357:        # get_track_by_path() runs on every watchdog and LUFS file event, and
  358:        # older databases were created without UNIQUE on file_path, so they have
  359:        # no implicit index to lean on.
  360:        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tracks_file_path ON tracks(file_path)")
  ```
  and `core/database.py:1278-1282` (`mark_track_downloaded`) writes `file_path` with no uniqueness check.
- **Reproduction / verification:** probe `%TEMP%\opencode\wn07_probe3.py` (old-style schema, `file_path TEXT` without `UNIQUE`):
  ```
  rows sharing the file: [(1, '...\song.mp3'), (2, '...\song.mp3')]
  duplicate groups: [(2, [1, 2], 100.0)]
  file still on disk: False
  survivor row file_path: ...\song.mp3 -> exists: False
  => DANGLING ROW
  ```
  (On a *current*-schema library the same script fails with `sqlite3.IntegrityError: UNIQUE constraint failed: tracks.file_path` — confirming the finding is schema-version dependent.)
- **Suggested fix:** delete the row first, then unlink only if no other row references the path (`SELECT 1 FROM tracks WHERE file_path = ?`), and re-order so a DB failure can never destroy the file first.
- **Fix side effects:** the file stays on disk when another row still needs it — correct, but the user must be told ("the file is still used by another entry").
- **Discovered by:** B

#### F-WN-07-4  [P2] — No de-duplication of playlist membership + name-keyed playlist identity ⇒ repeated imports/creates duplicate every track

- **File:** `core/api.py:2385-2396`; `core/api.py:3420-3434`; `core/database.py:1867-1890`; `core/database.py:1950-1999`
- **Confirmed:** yes
- **Description:** there is no single authority for "is this track already in this playlist?". `playlist_tracks` has no `UNIQUE(playlist_id, track_id)`; `add_to_playlist` and `add_tracks_to_playlist` blind-`INSERT`. At the same time `create_playlist_ex` **reuses** an existing playlist whose name matches case-insensitively and reports `created=False` — so a second import/creation with the same name appends to the existing playlist instead of starting a new one.
- **Cause:** playlist identity is the *name* rather than the row, and membership has no uniqueness constraint, so every "add again" is an append.
- **Trigger conditions:** importing the same playlist twice; pressing "Создать плейлист из локальных треков" twice (`ui/web_new_v2/js/profile.js:177-181` — the button stays enabled).
- **User impact:** a playlist that contains every track twice, with no way to tell from the UI. The user cannot delete one copy without deleting both.
- **Evidence:**
  ```python
  # core/database.py:1884-1890
  1884:                cursor.execute("SELECT id FROM playlists WHERE LOWER(name) = LOWER(?) LIMIT 1", (clean_name,))
  1885:                row = cursor.fetchone()
  1886:                if row:
  1887:                    return row["id"], False
  ...
  1890:                return cursor.lastrowid, True
  ```
  ```python
  # core/database.py:1962-1965 — unconditional INSERT, no uniqueness guard
  1962:                    cursor.execute(
  1963:                        "INSERT INTO playlist_tracks (playlist_id, track_id, position) VALUES (?, ?, ?)",
  1964:                        (playlist_id, track_id, next_pos),
  1965:                    )
  ```
  ```python
  # core/api.py:2393-2396 — the import loop re-adds every track every time
  2393:                track_id = self._core.db.ensure_track_exists(track)
  2394:                if not track_id or not self._core.db.add_to_playlist(playlist_id, track_id):
  2395:                    raise RuntimeError("Не удалось добавить все треки в локальный плейлист")
  ```
- **Reproduction / verification:** probe `%TEMP%\opencode\wn07_probe10.py`:
  ```
  === PROBE 14: create_local_playlist called twice (profile.js button) ===
    after 1st call: playlist_id= 1  entries= 3
    after 2nd call: playlist_id= 1  entries= 6  same playlist? True
  ```
  and probe `%TEMP%\opencode\wn07_probe1.py` (PROBE 1): `create_playlist_ex('Rock') -> 1 created= False`, `playlist_tracks rows: [(1, 1), (1, 1)]`.
- **Suggested fix:** add `UNIQUE(playlist_id, track_id)` to `playlist_tracks` (after de-duplicating existing rows) and make the adds `INSERT OR IGNORE`; give `create_playlist` an explicit "create" vs "get-or-create" split so the UI can tell the user when a playlist was reused.
- **Fix side effects:** the migration would have to clean existing duplicates first (the machinery exists: `core/database.py:968-980`); users who deliberately keep the same track twice in one playlist would lose that ability.
- **Discovered by:** B

#### F-WN-07-5  [P2] — A failed playlist import leaves orphan `tracks` rows behind

- **File:** `core/api.py:2389-2414`; `core/database.py:1054-1164`
- **Confirmed:** yes
- **Description:** the import loop calls `ensure_track_exists()` per track, each of which commits its own transaction. If a later track fails, the rollback deletes the *playlist* but not the track rows that were already created. The import is not one transaction.
- **Cause:** the rollback only undoes what it knows about (the playlist row). The track rows are created by a different, individually-committed call and are not tracked.
- **Trigger conditions:** any failure during the import loop — a DB error, a disk-full, a locked file, a provider returning a malformed track (`import_external_playlist` raises on a non-dict track at `core/api.py:2391-2392`).
- **User impact:** a failed import of a 500-track playlist leaves up to 500 rows in `tracks` with no file. They show up in the library view, in the track counts, in the smart-playlist filters and in the profile statistics — phantom entries the user never imported.
- **Evidence:**
  ```python
  2389:            added_count = 0
  2390:            for track in tracks:
  ...
  2393:                track_id = self._core.db.ensure_track_exists(track)
  2394:                if not track_id or not self._core.db.add_to_playlist(playlist_id, track_id):
  2395:                    raise RuntimeError("Не удалось добавить все треки в локальный плейлист")
  ...
  2408:            if playlist_id is not None and created:
  2409:                try:
  2410:                    self._core.db.delete_playlist(playlist_id)
  ```
  `delete_playlist` (`core/database.py:2018-2026`) deletes `playlist_tracks` and `playlists` only.
- **Reproduction / verification:** probe `%TEMP%\opencode\wn07_probe8.py`:
  ```
  === PROBE 11: a FAILED import leaves orphan rows in the tracks table ===
    import result: False ...
    tracks rows before: 0  after: 3  -> ORPHANS: 3
    playlists: []
  ```
- **Suggested fix:** collect the created track ids and delete them on rollback, and/or run the whole import in a single transaction (`DatabaseManager` already has `_write_lock` + `with self.conn:`).
- **Fix side effects:** a single transaction over hundreds of tracks holds the write lock for a long time; the id-tracking approach is cheaper but must not delete a track that already existed before the import.
- **Discovered by:** B

#### F-WN-07-6  [P2] — The creation path's track identity (title+artist) silently refuses to register a second, distinct local file

- **File:** `core/database.py:1094-1127`; `core/database.py:88` (`TRACK_RECORDING_COLUMNS`); `core/database.py:544-550`; `core/database.py:871-966`
- **Confirmed:** yes
- **Description:** `add_track` matches an existing row on `LOWER(title) = LOWER(?) AND LOWER(artist) = LOWER(?)` **only**. The merge migration in the same file explicitly states the opposite rule: "Two rows that merely share a title/artist — a different album, a different provider id, a different file, a different spelling, an unknown artist — are DIFFERENT recordings" and groups on `TRACK_RECORDING_COLUMNS = (title, artist, album, source, source_id, file_path)`. The two sides of the same concept disagree.
- **Cause:** the creation path keys on a subset of the identity columns. The second file therefore never becomes a row — it stays on disk, unregistered, and the scanner reports the *other* file as the scan result.
- **Trigger conditions:** two local files carrying the same title+artist tags (a very common case: the same track in two folders, an album and a "Single" edition, `Intro.mp3` / `Intro (Live).mp3`).
- **User impact:** the library silently omits a file the user owns; the file is unreachable from the app and unplayable through it. Because `_import_file` returns `db.get_track(track_id)`, the scan reports success with the wrong file.
- **Evidence:**
  ```python
  # core/database.py:1112-1127
  1112:                if name_is_meaningful(title, artist):
  1113:                    cursor.execute(
  1114:                        "SELECT id, cover_url, file_path FROM tracks WHERE " + TRACK_IDENTITY_SQL,
  1115:                        (title, artist),
  1116:                    )
  1117:                    row = cursor.fetchone()
  1118:                    if row:
  1119:                        t_id = row["id"]
  1120:                        if cover_url and not row["cover_url"]:
  1121:                            cursor.execute("UPDATE tracks SET cover_url = ? WHERE id = ?", (cover_url, t_id))
  1122:                        if file_path and not row["file_path"]:
  1123:                            cursor.execute(
  1124:                                "UPDATE tracks SET file_path = ?, is_downloaded = 1 WHERE id = ?",
  1125:                                (file_path, t_id),
  1126:                            )
  1127:                        return t_id
  ```
  vs `core/database.py:88`:
  ```python
  88:    TRACK_RECORDING_COLUMNS = ("title", "artist", "album", "source", "source_id", "file_path")
  ```
- **Reproduction / verification:** probe `%TEMP%\opencode\wn07_probe6.py`:
  ```
  row A id: 1 path: TrackA.mp3
  row B id: 1  same row as A? True
  db rows: [(1, 'Intro', 'Album One', 'TrackA.mp3')]
  B registered in the library? False
  B on disk (orphaned)? True
  ```
  (`album="Album Two"` and a different path were passed for B.)
- **Suggested fix:** make `add_track` use the same recording refinement as the migration (for `source="local"` the path should be the identity), and reuse one helper for "is this the same recording?".
- **Fix side effects:** existing libraries contain rows that the stricter rule would separate — the migration is idempotent and already safe, but the creation path change may surface rows the merge migration had collapsed differently.
- **Discovered by:** B

#### F-WN-07-7  [P2] — The tag editor rewrites the user's original media file in place, with no atomic write and no backup next to it

- **File:** `core/api.py:3962-3976`; `utils/tag_parser.py:237-397` (root cause owned by **WN-27**)
- **Confirmed:** yes (for the mutagen behaviour); the WN-07 part (no backup, no verification, full-file copy per edit) is confirmed
- **Description:** `update_track_tags` calls `utils.tag_parser.write_tags(file_path, ...)`, which (a) copies the **whole** media file to `%TEMP%` as a backup and (b) rewrites the original **in place** with mutagen. The "atomic rollback" only runs on a Python exception — it cannot run on a crash, a power loss or `os._exit`. mutagen's own `ID3.save()` is an in-place rewrite (`insert_bytes`/`delete_bytes` then `f.seek(0); f.write(data)`), so the docstring "writes atomically" is false.
- **Cause:** mutagen has no atomic-save primitive, and the code compensates with a copy-back on the exception path instead of writing to a sibling temp file and `os.replace()`-ing it (atomic on NTFS).
- **Trigger conditions:** a crash / power loss / forced kill during the tag write on a file larger than the tag block — the classic case is an `APIC` frame (cover art) that *grows* the file, because `insert_bytes` shifts the whole audio body first.
- **User impact:** the user's original music file is left truncated or body-shifted → unplayable, and the `%TEMP%` backup is never restored. The desktop has no backup feature (`core/database.py:527-536` says so explicitly).
- **Evidence:**
  ```python
  # utils/tag_parser.py
  248:    Safely write physical ID3v2/Vorbis/MP4 tags to an audio file using mutagen.
  249:    Checks write permissions, embeds cover art, and writes atomically.
  ...
  265:    backup_fd, backup_path = tempfile.mkstemp(prefix="aura_tag_backup_", suffix=os.path.splitext(filepath)[1])
  266:    os.close(backup_fd)
  267:    shutil.copy2(filepath, backup_path)          # full-file copy, every edit
  ...
  302:            tags.save(filepath, v2_version=3)   # in-place rewrite
  ...
  392:    except Exception as e:
  393:        # Atomic rollback on any mutagen write failure
  394:        if os.path.exists(backup_path):
  395:            shutil.copy2(backup_path, filepath)
  ```
  mutagen (`mutagen/id3.py`, `ID3.save`): `insert_bytes(f, new_size - old_size, old_size)` … `f.seek(0); f.write(data)` — no temp file, no rename.
- **Reproduction / verification:** `inspect.getsource(mutagen.id3.ID3.save)` on the project's own venv (3.14.7) shows the in-place shift+write shown above; no `os.replace`/`NamedTemporaryFile` anywhere in the write path. `core/api.py:3962-3964` also confirms the bridge writes to the original path with no copy of its own.
- **Suggested fix:** (a) in `write_tags`, write the tags to `<filepath>.<ext>.tmp` in the *same directory* and `os.replace()` it over the original — atomic on NTFS; keep the `%TEMP%` backup next to the original, not in `%TEMP%`; (b) skip the full-file `shutil.copy2` when the tag block does not grow.
- **Fix side effects:** `os.replace` needs write permission on the *directory*, not just the file — a read-only music folder would now fail where it previously succeeded; mutagen also needs a writable copy of the source, so the copy must be made first.
- **Discovered by:** B (the WN-27 side of the same root cause: `utils/tag_parser.py::write_tags`)

#### F-WN-07-8  [P3] — `export_playlist` silently overwrites an existing file

- **File:** `core/api.py:2429-2435`, `core/api.py:2483-2484`
- **Confirmed:** yes
- **Description:** the default destination `~/Music/<playlist>.m3u8` (falling back to `~/Downloads`, then `~`) is opened with mode `"w"` and no existence check. An existing file at that path is destroyed. The explicit `target_path` branch, by contrast, is correctly confined (see §3).
- **Cause:** the write is unconditional; the code checks the *extension* of the default name but not whether the file is already there.
- **Trigger conditions:** exporting a playlist whose name matches an existing M3U in `~/Music` (e.g. one the app wrote earlier, or one the user hand-edited).
- **User impact:** the user's own M3U file is silently replaced by the app's export. No prompt, no backup, no log line beyond the INFO export message.
- **Evidence:**
  ```python
  2429:            music_dir = os.path.expanduser("~/Music")
  ...
  2435:            out_file = os.path.join(music_dir, f"{safe_name}.m3u8")
  ...
  2483:            with open(out_file, "w", encoding="utf-8") as f:
  2484:                f.write("\n".join(m3u_lines) + "\n")
  ```
- **Reproduction / verification:** probe `%TEMP%\opencode\wn07_probe9.py`:
  ```
  === PROBE 12c: default export silently OVERWRITES an existing file ===
    export success: True
    file now: '#EXTM3U\n#PLAYLIST:Overwrite\n#EXTINF:0,A - T\nC:\\Users\\E8E5~1\\...'
  ```
  (the pre-existing content was `USER'S OWN IMPORTANT M3U CONTENT`).
- **Suggested fix:** refuse to overwrite, or write to `name (1).m3u8`; report the final path back to the UI (it already does).
- **Fix side effects:** re-exporting the same playlist would create a growing set of numbered files unless the UI offers to overwrite explicitly.
- **Discovered by:** B

#### F-WN-07-9  [P3] — N+1 in `get_playlist_tracks`: one redundant `SELECT * FROM tracks WHERE id=?` per track

- **File:** `core/api.py:2551-2562` → `core/api.py:1161-1193`
- **Confirmed:** yes
- **Description:** the bridge loads the playlist with one JOIN query (`SELECT t.*, pt.position, …`), then calls `_enrich_track_lufs(item)` for every track. `_enrich_track_lufs` re-reads the row from the DB whenever `loudness_lufs` is NULL — which is the normal case for any track that was never loudness-scanned. The value it is looking for is already in the row it was handed.
- **Cause:** the enricher was written for the "track dict came from a search result" case and always assumes it must fetch; the playlist path already has the full row.
- **Trigger conditions:** every playlist view render; also `get_track_info` (`core/api.py:2537-2539`) issues 2 SELECTs for one track.
- **User impact:** measurable but modest — 6 tracks → 6 extra PK point-lookups (measured), 500 tracks → 500 extra lookups per render, on the bridge thread.
- **Evidence:**
  ```python
  # core/api.py:2551-2562
  2551:                db_tracks = self._core.db.get_playlist_tracks(playlist_id) or []
  ...
  2561:                        self._enrich_track_lufs(item)
  ```
  ```python
  # core/api.py:1166-1183
  1166:        lufs = track_dict.get("loudness_lufs") if track_dict.get("loudness_lufs") is not None else track_dict.get("lufs")
  1167:        if lufs is not None:
  ...
  1172:        try:
  1173:            db_track = None
  1174:            t_id = track_dict.get("id") or track_dict.get("track_id")
  1175:            if t_id:
  1176:                try:
  1177:                    db_track = self._core.db.get_track(int(t_id))
  ```
- **Reproduction / verification:** probe `%TEMP%\opencode\wn07_probe7.py`:
  ```
  === PROBE 9: get_playlist_tracks N+1 (one extra SELECT per track) ===
    tracks returned: 6
    extra db.get_track() calls: 6 (playlist has 6 tracks)
  === PROBE 10: get_track_info issues a redundant second SELECT ===
    db.get_track() calls for one get_track_info: 2
  ```
- **Suggested fix:** in the playlist path, read `loudness_lufs` straight from the row (it is in `SELECT t.*`); give `_enrich_track_lufs` a "row already loaded" mode.
- **Fix side effects:** none.
- **Discovered by:** B

#### F-WN-07-10  [P3] — The duplicate scan re-hashes the whole library on every invocation; fingerprints are never persisted

- **File:** `core/api.py:3876-3882`; `services/audio_fingerprint_service.py:26-113`; `core/database.py` (no `fingerprint` column — `grep fingerprint` → no match)
- **Confirmed:** yes
- **Description:** `find_duplicate_tracks` recomputes an MD5 over head/middle/tail of every local file on every call. Nothing is cached: there is no fingerprint column, and `tracks.file_size` is not even consulted. The scan runs synchronously on the bridge thread.
- **Cause:** the fingerprint is treated as a transient computation rather than a property of the file.
- **Trigger conditions:** every "Найти дубликаты" click; the UI calls it on every settings-panel open (`ui/web_new_v2/js/settings.js:287-289`).
- **User impact:** 192 KiB read + MD5 per file, every time. Measured on a warm SSD: 0.05 s for 150 files ⇒ ~1.7 s for 5,000 tracks. On a spinning disk, a network share or a cold page cache this becomes tens of seconds of a blocked bridge call with no progress feedback.
- **Evidence:**
  ```python
  # services/audio_fingerprint_service.py:36-51
  36:            with open(filepath, "rb") as f:
  37:                head = f.read(sample_bytes)          # 64 KiB
  38:                md5_hash.update(head)
  39:
  40:                if file_size > sample_bytes * 3:
  41:                    f.seek(file_size // 2)
  42:                    mid = f.read(sample_bytes)         # 64 KiB
  ...
  45:                    f.seek(file_size - sample_bytes)
  46:                    tail = f.read(sample_bytes)        # 64 KiB
  ```
- **Reproduction / verification:** probe `%TEMP%\opencode\wn07_perf.py`:
  ```
  find_duplicates over 150 files of 4 MB: 0.05 s  (0.3 ms/file)
    -> extrapolated to 5000 tracks: 1.7 s
    bytes hashed per file: 192 KiB -> 28 MiB read for 150 files
  ```
- **Suggested fix:** persist the fingerprint (plus size+mtime) in `tracks.metadata_json` or a dedicated column and reuse it while size+mtime are unchanged; move the scan to a worker thread with progress events.
- **Fix side effects:** a stale fingerprint after a file is edited in place (size+mtime covers it).
- **Discovered by:** B

#### F-WN-07-11  [P3] — `_auto_save_favorite` walks the whole downloads directory on every like

- **File:** `core/api.py:2698-2712`
- **Confirmed:** yes
- **Description:** the auto-download quota is checked by listing `~/.nedotify/downloads` and `stat`-ing every file, on the bridge thread, on every favourite — with no memoisation, while `utils/cache_manager.py::get_cache_size` already implements a TTL-cached size for the other library folders.
- **Cause:** a second, uncached implementation of "how much disk does the library use" inside the bridge.
- **Trigger conditions:** every like of a streaming track when `auto_download_favorites` is on.
- **User impact:** measured 26 ms for a 2,000-file downloads dir, ~0.26 s for 20,000 files — a visible pause on the like action that grows with the library and is worst on a slow disk.
- **Evidence:**
  ```python
  2698:        used = 0
  2699:        try:
  2700:            dl_dir = os.path.join(os.path.expanduser("~"), ".nedotify", "downloads")
  2701:            if os.path.isdir(dl_dir):
  2702:                for name in os.listdir(dl_dir):
  2703:                    fp = os.path.join(dl_dir, name)
  2704:                    try:
  2705:                        if os.path.isfile(fp):
  2706:                            used += os.path.getsize(fp)
  ```
  vs the cached alternative, `utils/cache_manager.py:78-93` (`get_cache_size`, 60 s TTL, `os.scandir`).
- **Reproduction / verification:** probe `%TEMP%\opencode\wn07_perf.py`:
  ```
  === _auto_save_favorite download-dir scan cost ===
    2000-file download dir scan: 25.8 ms  -> 20000 files: 0.26 s
  ```
- **Suggested fix:** reuse a TTL-cached size for the downloads folder (the `cache_manager` pattern), or keep a running byte counter in the download store.
- **Fix side effects:** a TTL means the quota can be exceeded slightly between checks; the current code has the same race, just more expensively.
- **Discovered by:** B

#### F-WN-07-12  [P3] — `open_local_file` does nothing when the chosen file is already in the library

- **File:** `core/api.py:3436-3459`; `utils/file_scanner.py:52-56`, `utils/file_scanner.py:111-116`
- **Confirmed:** yes
- **Description:** `open_local_file` treats "scan returned a track" as "the file was imported". But `FileScanner._import_file` returns `None` for a file that is already in the database. So for an already-known file the list stays empty and the bridge returns `False` — no playback, no message, nothing happens.
- **Cause:** the bridge conflates "import this file" with "play this file"; the scanner's "already known → None" contract means "nothing to import", not "nothing to play".
- **Trigger conditions:** the user picks a file that is already in the library (the common case after the first import).
- **User impact:** the "open local file" action appears broken for exactly the files the user already has. The file dialog opens, the user picks a file, and nothing plays.
- **Evidence:**
  ```python
  # core/api.py:3447-3459
  3447:            imported = []
  3448:            for file_path in res:
  3449:                meta = self._core.scanner.scan_single_file(file_path)
  3450:                if meta:
  3451:                    imported.append(meta)
  3452:
  3453:            if imported:
  3454:                self._emit("library_updated", True)
  3455:                self.play_track(imported[0], track_list=imported, index=0)
  3456:                return True
  ...
  3459:        return False
  ```
  ```python
  # utils/file_scanner.py:113-116
  113:        # Check if already in database
  114:        existing = self.db.get_track_by_path(filepath)
  115:        if existing:
  116:            return None
  ```
- **Reproduction / verification:** probe `%TEMP%\opencode\wn07_probe10.py`:
  ```
  === PROBE 15: open_local_file on a file already in the library ===
    open_local_file() -> False  (expected True + playback)
  ```
- **Suggested fix:** look the file up with `get_track_by_path` and play the existing row when the scan returns `None`.
- **Fix side effects:** `library_updated` would then be emitted for files that were not new — should be emitted only when something was actually added.
- **Discovered by:** B (Role A will likely see the same symptom from the correctness side)

#### F-WN-07-13  [P2] — Remote M3U / JSON / text playlist links can never be imported

- **File:** `core/api.py:2362-2378` (bridge, WN-07); root cause in `services/playlist_import_service.py:39-58` (**owner: WN-24**)
- **Confirmed:** yes
- **Description:** `PlaylistImportService.resolve()` routes any target whose name ends in `.m3u`, `.m3u8`, `.json` or `.txt` to `_resolve_local_file()`, which requires a file that exists on this disk. The bridge only forwards `http(s)` URLs (the SSRF gate at `core/api.py:2364-2367` rejects anything else), so the local branch is unreachable and a remote playlist link always dies with "Файл плейлиста не найден: &lt;the URL&gt;".
- **Cause:** the extension test in the callee is applied before the URL test, so a URL is mistaken for a local file name.
- **Trigger conditions:** the user pastes a link to a `.m3u`/`.m3u8`/`.json`/`.txt` playlist — the exact formats the error message at `services/playlist_import_service.py:58` advertises as supported.
- **User impact:** the advertised "M3U/M3U8, JSON и текстовых списков" import support does not work from the UI; the error message names the user's own URL as a missing file, which is confusing.
- **Evidence:**
  ```python
  # services/playlist_import_service.py:45-47
  45:        # 1. Local file or M3U/JSON text content
  46:        if os.path.exists(target) or target.endswith((".m3u", ".m3u8", ".json", ".txt")):
  47:            return self._resolve_local_file(target)
  ```
  ```python
  # services/playlist_import_service.py:221-222
  221:        if not os.path.exists(target):
  222:            raise PlaylistImportError(f"Файл плейлиста не найден: {target}")
  ```
- **Reproduction / verification:** probe `%TEMP%\opencode\wn07_probe11.py`:
  ```
  'https://example.com/list.m3u8' -> PlaylistImportError: Файл плейлиста не найден: https://example.com/list.m3u8
  'https://example.com/list.m3u'  -> PlaylistImportError: Файл плейлиста не найден: https://example.com/list.m3u
  'https://example.com/list.json' -> PlaylistImportError: Файл плейлиста не найден: https://example.com/list.json
  'https://example.com/list.txt'  -> PlaylistImportError: Файл плейлиста не найден: https://example.com/list.txt
  ```
- **Suggested fix:** in the callee, test the scheme first (`urlparse(target).scheme in ('http','https')` → fetch and parse the body) and only fall back to the local-file branch for a path that exists. Ownership: **WN-24** — do not double-report there.
- **Fix side effects:** fetching a remote playlist means SSRF-safe fetching with a size cap in the callee; the bridge's existing SSRF gate only validates the *entry* URL.
- **Discovered by:** B

---

### 3. Clean areas

Checked and found correct:

- **`export_playlist(target_path=…)` path confinement** (`core/api.py:2436-2450`): `realpath` + `os.path.commonpath([target_abs, home_abs]) == home_abs` + extension allow-list (`.m3u`/`.m3u8` only) + the parent directory must exist + `ValueError` (different drives) treated as "not inside". Verified empirically on this machine: `..\..\Windows\Temp\evil.m3u8` → rejected; `..\..\evil.m3u8` → rejected; `sub\..\x.m3u8` → accepted (correctly inside home); `commonpath` is case-insensitive on Python 3.14/Windows. Pinned by `tests/test_api_f1_audit.py:144-171`. The playlist name is sanitised into the file name (`core/api.py:2423`), so Windows-illegal characters cannot reach the file name; reserved device names (`CON`, `PRN`) turned out to be creatable on this Windows build, so that was checked and is *not* a finding.
- **`choose_cover_image` / `select_avatar`** use the native file dialog and write only into `~/.nedotify/covers` / `~/.nedotify/avatars`; the proxy's `_safe_avatar_path` / `_safe_cover_path` (`core/proxy.py:275-282`) confine serving to those roots with an image-extension allow-list and realpath containment.
- **`_store_artist_binding` does not build a path** (`core/api.py:3461-3475`): `binding_key`/`name_key` (`services/artist_identity.py:9-38`) normalise to NFKC+casefold+ё→е, and the result is a JSON object key inside the `settings` blob. No filesystem component, no traversal surface.
- **`services/smart_playlists.py`** rule handling is a strict allow-list (`normalize_rule`, lines 20-51): unknown keys rejected, exact types checked, integer ranges bounded, `sort` validated against a fixed map. Every SQL *value* is parameterised; the only interpolated fragment is `self.SORTS[rule['sort']]`, and `sort` is validated against that same map before use. The artist filter escapes `%`/`_`/`\` and declares `ESCAPE '\'`.
- **Database concurrency model** (`core/database.py:179-205`): WAL, `synchronous=NORMAL`, `busy_timeout=30000`, `PRAGMA foreign_keys=ON`, one connection per thread (`threading.local`), one process-wide `RLock` for writes. No lock-ordering or double-lock problem found in the reviewed range; `_write_lock` is an `RLock`, so the nested `with self.conn:` + `with self._write_lock:` patterns in `create_playlist_ex` and `_cleanup_duplicate_empty_system_playlists` are safe.
- **`update_track_tags` ordering**: the physical tag write happens before the DB update and the DB is left untouched when the write fails (`core/api.py:3962-3990`) — the right order for a physical/DB pair.
- **`toggle_favorite` / `_auto_save_favorite`**: the feature is off by default, local files are skipped, un-liking never deletes, the quota is honoured with a reason string, and a failing side-effect cannot break the like itself (`core/api.py:2615-2638`). Pinned by `tests/test_auto_save_favorites.py`.
- **The de-duplication *migration*** (`core/database.py:524-634`, `871-980`) is well built and is the model the runtime path should follow: snapshot before merge, one transaction, idempotent, history/playlist/download-queue re-pointed at the survivor, a corrective restore migration, and everything named in a WARNING. Pinned by `tests/test_dup_cleanup_migration.py` (665 lines, 30+ cases).
- **`create_playlist_ex` correctly reports `created`** so the import rollback can never delete a playlist the user already had (`core/database.py:1867-1890`; `tests/test_api_f1_audit.py:287-316`).
- **`get_playlists()` is a pure reader** — the duplicate-system-playlist cleanup was deliberately moved into `create_playlist` so a view render never writes (`core/database.py:1892-1929`).
- **`smart_playlists` does not use `DatabaseManager`'s write path**: it takes `self.db._write_lock` and `with self.db.conn:` itself, so it participates in the same serialisation as the rest of the writers. (The layering objection is filed as ARCH-1, not as a defect.)

---

### 4. Coverage gaps

- The real `~/.nedotify/` library was never opened (ground rules). The dangling-row finding (F-3) was therefore reproduced on a synthetic old-schema database, not on a real user library. Whether a specific user's library actually holds two rows with one `file_path` is unverified.
- The proxy was not started; the exfiltration step of F-1 was verified by calling `core.proxy._safe_cover_path()` directly rather than over HTTP. The HTTP layer of `/api/cover` was read, not executed.
- The live network paths of `PlaylistImportService` (YouTube / SoundCloud) were exercised only once, for routing; the shape of a real resolved playlist and the behaviour of `_enrich_soundcloud_tracks` under load were not measured.
- `write_tags` was not exercised on a real multi-MB FLAC/MP3: the synthetic files I produced could not be parsed by mutagen ("can't sync to MPEG frame"), so the F-7 atomicity claim rests on mutagen's own `ID3.save` source plus the code reading, not on a measured crash. A crash-injection test (kill the process between `insert_bytes` and the final write) would be the definitive check.
- `core/app.py` wiring for `playlist_importer` / `audio_fingerprint` / `scanner` was grepped and partially read, not audited in full (WN-02).
- `core/proxy.py`'s `/api/stream` path was read to trace the client-payload → DB → filesystem chain requested for this area, but the full proxy was not audited (WN-11).
- The `android/` subtree was not opened (out of scope for this run).
- Only `core/api.py` L2355–2754, L3390–3479 and L3866–4025 were reviewed in the bridge; the surrounding methods were read only for call-chain context.

---

### 5. Architecture improvements (ARCH)

These are improvements without a proven defect; they are listed separately from the findings above.

**ARCH-1 — Two playlist models, two identities, two normalisation rules, and a service that reaches into the persistence layer's privates.**
`playlists` + `playlist_tracks` (identity = case-insensitive *name*, `core/database.py:1884`) co-exist with `smart_playlists` (identity = rowid, `services/smart_playlists.py:91-119`) — two different concepts behind the same word. Name normalisation is implemented three times with three rules: `LOWER(name)=LOWER(?)` in the DB, `name.strip()` + length ≤ 120 in `smart_playlists._name`, and NFKC + casefold + ё→е in `artist_identity.name_key`. `services/smart_playlists.py` uses `self.db.conn`, `self.db.conn.execute` and `self.db._write_lock` directly instead of `DatabaseManager` methods, so the transaction and lock invariants the rest of the app depends on are re-implemented outside the layer that owns them.
*Direction:* one playlist identity model (explicit `playlist_id` semantics, name uniqueness as an explicit policy), one shared name-normalisation helper, and move the smart-playlist SQL behind `DatabaseManager` methods.

**ARCH-2 — No single authority for "is this track already in this playlist?"**
The only de-duplication in the entire playlist domain is the one-shot migration statement `_remove_exact_duplicate_playlist_entries` (`core/database.py:968-980`). Every runtime path (`add_to_playlist`, `add_tracks_to_playlist`, the API's `add_to_playlist`, the import loop) blind-`INSERT`s. A `UNIQUE(playlist_id, track_id)` index plus `INSERT OR IGNORE` would make the invariant structural instead of procedural.
*Direction:* enforce it in the schema and let the UI report "already in playlist" from the same constraint.

**ARCH-3 — "The same track" is defined twice with two different meanings**
`add_track` keys on `(title, artist)`; `_plan_track_merges` / `TRACK_RECORDING_COLUMNS` keys on `(title, artist, album, source, source_id, file_path)`. The shared-constant test (`tests/test_dup_cleanup_migration.py:535-551`) only asserts that the SQL *expression* is shared, so the semantic disagreement passes CI. This is the root of F-6 and of the class of bug the migration's own docstring warns about.
*Direction:* one `is_same_recording(a, b)` helper used by the creation path, the merge planner and the scanner.

**ARCH-4 — The duplicate domain is split over three layers with three notions of "duplicate"**
Content hash (`services/audio_fingerprint_service.py`), metadata identity (`core/database.py::_plan_track_merges`) and per-playlist pair (`_remove_exact_duplicate_playlist_entries`). The merge machinery that knows how to preserve history/playlists/favourites already exists in the DB layer — it is simply not reachable from the runtime duplicate-delete path (F-2).
*Direction:* move "remove a duplicate" into the DB layer next to the merge, so the one algorithm that understands the invariants is the only one used.

**ARCH-5 — Two implementations of "how much disk does the library use"**
`utils/cache_manager.py::get_cache_size` (TTL-cached, `os.scandir`, covers/streams/temp) and the inline uncached `os.listdir` + `getsize` scan of the downloads folder in `core/api.py:2698-2712`. Neither knows about the other, and the downloads folder — the part that actually grows — is the one without a cache.
*Direction:* one storage-accounting service covering all four `~/.nedotify` subtrees, with a TTL cache and a dirty flag.

**ARCH-6 — `core/database.py::get_smart_playlist_tracks` (lines 2001-2002) is a misleading stub**
It delegates to `get_playlist_tracks` — i.e. it returns *ordinary* playlist tracks under a name that promises smart-playlist tracks. Any caller that trusts the name gets the wrong thing.
*Direction:* delete it, or implement it against the same table the service uses.

**ARCH-7 — The bridge hands raw DB rows to the frontend and each consumer re-normalises them**
`get_playlists`, `get_playlist_tracks` and `get_track_info` return raw row dicts; the UI then re-derives `cover`/`cover_url`, coerces `source_id` to a string, and the bridge itself probes for both `id` and `ID` spellings (`core/api.py:2421`). There is no serialisation contract for a "track" or a "playlist", so every new consumer re-implements the mapping.
*Direction:* one `serialize_track()` / `serialize_playlist()` in the bridge layer, used by every read method.

**ARCH-8 — The playlist import is N+1 transactions**
`import_external_playlist` performs one commit per track insert and one per membership insert (`core/api.py:2389-2396`), while `DatabaseManager` already offers a batch primitive (`add_tracks_to_playlist`, one transaction) that the import does not use. That is both the perf issue behind F-5 and the reason the rollback is incomplete.
*Direction:* one transaction for the whole import, using the batch helper, with the created-track ids tracked for the rollback.
