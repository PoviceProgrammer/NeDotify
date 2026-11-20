## AREA WN-27 — Utility modules — ROLE A

### 1. Scope reviewed

**Files opened (full read, physical 1-based lines):**

| File | Lines read | Notes |
|---|---|---|
| `utils/cache_manager.py` | 1–453 (whole file, 398 non-empty) | `CacheManager` L16–453 |
| `utils/file_scanner.py` | 1–181 (whole file, 149 non-empty) | `is_audio_file` L19, `FileScanner` L26–181 |
| `utils/search_query.py` | 1–101 (whole file, 92 non-empty) | `_distance` L13, `suggest_search_queries` L31 |
| `utils/stream_urls.py` | 1–26 (whole file, 22 non-empty) | `stream_url_expired` L7 |
| `utils/tag_parser.py` | 1–398 (whole file, 340 non-empty) | `is_audio_file` L26, `parse_tags` L32, `extract_embedded_lyrics` L121, `_get_tag` L145, `_extract_cover` L156, `save_cover_to_file` L211, `write_tags` L237 |
| `utils/url_safety.py` | 1–37 (whole file, 31 non-empty) | `is_safe_media_url` L13 |

**Callees traced into other areas (read for caller-side context, not reviewed here):**

- `core/api.py` L155–199 `_is_ssrf_safe_url`, L3030–3069 `get_storage_info`, L3425–3474 `open_local_file` → `scanner.scan_single_file`, L3595–3638 `_clean_stream_cache`, L3640–3683 `prefetch_track`, L3910–4000 `update_track_tags`, L4021–4129 storage/quota, L4219–4221 `get_search_suggestions`.
- `core/database.py` L82 `TRACK_IDENTITY_SQL`, L148–227 thread-local connection + WAL, L1054–1176 `add_track`, L1172–1176 `get_track_by_path`, L2134–2242 `set_cached_file` / `get_cached_stream` / `cache_stream` / `cleanup_expired_cache`.
- `core/app.py` L160–185 (10-min `cleanup_expired_cache` loop), L508–586 `cleanup()` (incl. `cache._executor.shutdown(wait=False)` at L574).
- `core/proxy.py` L23 (`_is_ssrf_safe_url` re-export), L115–169 (cover roots / extensions), L797–798, L805–854, L1180–1254 (stream cache write: temp → `os.replace` → `db.set_cached_file`).
- `core/downloader.py` L16, L629–662 `is_safe_media_url` guards; `core/download_transfer.py` L9, L67.
- `audio/engine.py` L12, L160–219 and L425–464 `is_safe_media_url` guards.
- `services/lyrics_lookup.py` L321–322 (`extract_embedded_lyrics` consumer); `services/smart_playlists.py` L156–174 (`available_only`); `services/watchdog_service.py` L104–129 (`scanner._import_file`); `core/offline.py` L17–74.
- `ui/web_new_v2/js/search.js` L1046–1069, `js/player.js` L1440–1441, `js/utils.js` L1487–1488 (reachability of the three bridge entry points).
- `setup_pyinstaller.spec` L104 (`console=False`) and `main.py` L88–92 (`sys.stdout.reconfigure` guarded by `except AttributeError`).
- mutagen 1.48.1 source in `.venv_win` (`mutagen/_file.py` `File()`, `mutagen/id3/_file.py` `ID3.save`, `mutagen/_util.py` `insert_bytes`/`delete_bytes`, `mutagen/flac.py` `Picture`, `mutagen/mp4/__init__.py` `MP4FreeForm`, `mutagen/asf.py` `ASFTags.__setitem__`).

**Runtime verification** (scratch scripts under `%TEMP%\opencode`, repo untouched; interpreter `.venv_win\Scripts\python.exe`):
`wn27_probe.py` (WAV/OGG/corrupt-file/tag-write probes), `wn27_probe2.py` (in-place mutation, suggestion perf, purge semantics), `wn27_probe3.py` (USLT repr, artist fallback, `_distance` vs brute force), `wn27_probe4.py` (`_distance` vs reference OSA Damerau–Levenshtein).

---

### 2. Findings

#### F-WN-27-1  [P1] — `write_tags` is NOT atomic: the user's audio file is rewritten in place while the docstring claims "writes atomically"

- **File:** `utils/tag_parser.py:249` (docstring), `utils/tag_parser.py:264-267` (backup), `utils/tag_parser.py:302` / `326` / `347` / `370` / `386` (in-place saves), `utils/tag_parser.py:388-397` (rollback)
- **Confirmed:** yes
- **Description:** `write_tags` rewrites the user's audio file **in place** through mutagen. mutagen's `ID3.save()` grows/shrinks the file with `insert_bytes`/`delete_bytes` and then overwrites the tag region with `f.write(data)` — all on the same open file handle. There is no temp-file + `os.replace`. The only safety net is a full copy of the file placed in the **system temp directory** (`tempfile.mkstemp`), which is deleted on success and restored only when a *Python exception* is raised. A hard crash (power loss, `TerminateProcess`, "End task", OOM kill) inside the write window leaves the audio payload shifted/interleaved with zeros and the backup stranded in `%TEMP%`.
- **Cause:** the implementation is a *backup + in-place mutation + exception-only rollback*, i.e. the classic non-atomic pattern; the backup is also placed on a different volume than the music file, so the rollback itself is a non-atomic cross-volume copy.
- **Trigger conditions:** the user edits tags of a track (`update_track_tags` → `js/utils.js:1488`) while the app is killed / the machine loses power during the ~milliseconds-to-seconds mutagen spends rewriting the file. Larger files (FLAC, WAV) widen the window because `move_bytes` copies the whole audio body.
- **User impact:** the user's only copy of a music file can be corrupted (audio payload zeroed) with no automatic recovery path; the docstring's "writes atomically" guarantee is false, so the risk was believed to be covered.
- **Evidence:**
  ```python
  # utils/tag_parser.py:247-249
  """
  Safely write physical ID3v2/Vorbis/MP4 tags to an audio file using mutagen.
  Checks write permissions, embeds cover art, and writes atomically.
  """
  # utils/tag_parser.py:264-267
  backup_fd, backup_path = tempfile.mkstemp(prefix="aura_tag_backup_", suffix=os.path.splitext(filepath)[1])
  os.close(backup_fd)
  shutil.copy2(filepath, backup_path)
  # utils/tag_parser.py:302
  tags.save(filepath, v2_version=3)
  # utils/tag_parser.py:388-397
  if os.path.exists(backup_path):
      os.remove(backup_path)
  return True
  except Exception as e:
      # Atomic rollback on any mutagen write failure
      if os.path.exists(backup_path):
          shutil.copy2(backup_path, filepath)
  ```
  mutagen 1.48.1 `mutagen/id3/_file.py::ID3.save`:
  ```python
  if (old_size < new_size):
      insert_bytes(f, new_size - old_size, old_size)
  elif (old_size > new_size):
      delete_bytes(f, old_size - new_size, new_size)
  f.seek(0)
  f.write(data)
  ```
- **Reproduction / verification:** `wn27_probe2.py` section A — after `write_tags(mp3, title=...)` the file grew in place (16 680 → 17 798 bytes) and **no** sibling temp file was created (`siblings before: ['song.mp3']` / `siblings after: ['song.mp3']`); mutagen's `insert_bytes` source shows `resize_file(fobj, size)` + `move_bytes(fobj, offset+size, offset, movesize)` on the user's file. `wn27_probe2.py` also shows the backup is created in `%TEMP%` (`copy2 called with: ('...\\AppData\\Local\\Temp\\aura_tag_backup_uo0n_htp.wav', '...\\song.mp3')`), i.e. not next to the media.
- **Suggested fix:** write to a sibling temp file in the **same directory** as the media, `os.replace()` it over the original, and keep the in-`%TEMP%` copy only as a secondary safety net; or use `os.replace` semantics explicitly and drop the "atomically" claim from the docstring.
- **Fix side effects:** `os.replace` on the same volume is atomic but changes the file identity (ACLs/inherited permissions of the original are replaced by the temp file's) and drops the original's creation time; a same-directory temp file also needs a write check on the media's directory, which may be read-only even when the file itself is writable.
- **Discovered by:** A

#### F-WN-27-2  [P1] — OGG cover extraction returns the FLAC picture *block* instead of the image bytes → every OGG cover is a non-image file

- **File:** `utils/tag_parser.py:180-189`
- **Confirmed:** yes
- **Description:** for `.ogg`, `_extract_cover` base64-decodes the `metadata_block_picture` value and returns it verbatim as `cover_data`. That value is a serialised **FLAC `PICTURE` metadata block** (4-byte picture type + MIME length + MIME + description + dimensions + the image bytes), *not* raw image data. `save_cover_to_file` then writes those bytes to `~/.nedotify/covers/cover_<id>.png` and the proxy serves it as `image/png`. The file is not a PNG, so the browser cannot decode it and the cover is broken for **every** OGG file.
- **Cause:** missing the `mutagen.flac.Picture` decode step; the correct value is `Picture(base64.b64decode(...)).data` (and `.mime` for the real MIME).
- **Trigger conditions:** any Ogg Vorbis file that carries a `metadata_block_picture` (i.e. essentially every tagged OGG). Note the asymmetry: `write_tags` L362-368 writes a *correct* `metadata_block_picture` (`pic.write()`), so a cover the app itself embeds is also mis-read back.
- **User impact:** the library and the player show a broken/missing cover art for OGG tracks; the broken file also permanently occupies the covers cache.
- **Evidence:**
  ```python
  # utils/tag_parser.py:180-189
  elif ext == '.ogg':
      try:
          ogg = OggVorbis(filepath)
          # OGG stores pictures in metadata_block_picture
          import base64
          if 'metadata_block_picture' in ogg:
              data = base64.b64decode(ogg['metadata_block_picture'][0])
              return data, 'image/png'
  ```
- **Reproduction / verification:** `wn27_probe.py` section 2 — `Picture.write()` → base64 → `b64decode` gives 119 bytes starting with `b'\x00\x00\x00\x03\x00\x00\x00\nimage/jp'` (a picture block), `decoded == png bytes? False`, while `Picture(raw).data == png bytes? True`. The MIME is additionally hard-coded to `image/png` regardless of the picture's real MIME.
- **Suggested fix:** decode with `mutagen.flac.Picture(base64.b64decode(value)).data` / `.mime`; fall back to sniffing the magic bytes when the MIME is unknown.
- **Fix side effects:** none material; the extracted bytes get smaller (the block header is dropped), so previously written `cover_<id>.png` files must be re-imported to be repaired.
- **Discovered by:** A

#### F-WN-27-3  [P1] — `write_tags` fails outright on `.wav` / `.aac` / `.wma` although all three are in `SUPPORTED_FORMATS`

- **File:** `utils/tag_parser.py:23` (`SUPPORTED_FORMATS`), `utils/tag_parser.py:372-386` (the `else` fallback branch)
- **Confirmed:** yes (`.wav` reproduced end-to-end; `.aac`/`.wma` confirmed from mutagen's class contracts)
- **Description:** the `else` branch of `write_tags` claims to be a "Fallback for other formats with EasyID3/EasyMutagen" and does `audio['title'] = [str(title)]`. But `MutagenFile(path, easy=True)` only wraps **MP3/FLAC/OggVorbis/MP4/TrueAudio** in an "Easy" class; for `.wav` it returns `mutagen.wave.WAVE`, for `.aac` `mutagen.aac.AAC`, for `.wma` `mutagen.asf.ASF`. Those expose raw tag objects, so assigning a `list[str]` raises (`ID3._setitem`: `"%r not a Frame instance"`, `ASFTags.__setitem__`: requires `ASFValue`). The exception is converted into `RuntimeError`, and the rollback path then **restores the original file** — the tag edit is impossible.
- **Cause:** the fallback branch assumes the "easy" dict interface, which mutagen only provides for a subset of formats; `SUPPORTED_FORMATS` was not narrowed to the formats the writer actually supports.
- **Trigger conditions:** the user opens a `.wav` (offered in the open dialog at `core/api.py:3441`: `*.mp3;*.flac;*.wav;*.ogg;*.m4a`) or a `.wma`/`.aac` and edits its tags via the track editor (`js/utils.js:1487`).
- **User impact:** `update_track_tags` returns `{"success": false, "error": "Ошибка при записи тегов в файл: ['Hello'] not a Frame instance"}` — an English mutagen internal message in a Russian UI, and the user's edit is silently discarded (the file is rolled back to its original state).
- **Evidence:**
  ```python
  # utils/tag_parser.py:23
  SUPPORTED_FORMATS = {'.mp3', '.flac', '.wav', '.ogg', '.m4a', '.wma', '.aac'}
  # utils/tag_parser.py:372-386
  else:
      # Fallback for other formats with EasyID3/EasyMutagen
      audio = MutagenFile(filepath, easy=True)
      if audio is not None:
          if title is not None:
              audio['title'] = [str(title)]
  ```
- **Reproduction / verification:** `wn27_probe.py` section 1 — a `wave`-module-generated `.wav` yields `MutagenFile(wav, easy=True) -> <class 'mutagen.wave.WAVE'>` with `tags: None`; `write_tags(wav, title="Hello", artist="World")` raised `RuntimeError: Ошибка при записи тегов в файл: ['Hello'] not a Frame instance` and the file was left unchanged (`after write_tags, title='sample' artist='Unknown Artist'`).
- **Suggested fix:** handle WAV/AAC through explicit `ID3`/`EasyID3` frames and WMA through `ASFUnicodeAttribute`, or narrow `SUPPORTED_FORMATS`/the file-dialog filter to the formats the writer really supports and return a clear "format not supported for tag editing" message.
- **Fix side effects:** narrowing `SUPPORTED_FORMATS` also changes `AUDIO_EXTENSIONS` in `utils/file_scanner.py:16` (derived from it) and therefore what `core/proxy.py`'s `AUDIO_EXTENSIONS` mirror implies; WAV/ASF/AAC can hold ID3 tags, so writing them explicitly is preferable to dropping them.
- **Discovered by:** A

#### F-WN-27-4  [P2] — `extract_embedded_lyrics` returns Python reprs for MP3 (USLT) and M4A (©lyr) lyrics

- **File:** `utils/tag_parser.py:131-140`
- **Confirmed:** yes
- **Description:** the MP3 branch does `texts.append(str(audio.tags[key].text))`. `USLT.text` is a **list** of strings, so `str()` yields `"['line one', 'line two']"`. The MP4 branch does `str(v) for v in audio.tags.get('\xa9lyr', [])`; mutagen stores `©lyr` as a freeform atom, i.e. an `MP4FreeForm` (a `bytes` subclass), so `str(v)` yields `"b'la la la'"`. Only the Vorbis branch (plain `str` values) is correct.
- **Cause:** the frame payloads are not unwrapped — `USLT.text` needs `"\n".join(...)` and `MP4FreeForm` needs `bytes(v).decode('utf-8', 'replace')`.
- **Trigger conditions:** any MP3 with a `USLT` frame or any M4A with a `©lyr` atom.
- **User impact:** `services/lyrics_lookup.py:321-322` puts this string straight into the lyrics view, so the user sees Python list/bytes syntax instead of the lyrics.
- **Evidence:**
  ```python
  # utils/tag_parser.py:131-140
  if ext == '.mp3':
      for key in audio.tags:
          if key.startswith('USLT'):
              texts.append(str(audio.tags[key].text))
  elif ext in ('.m4a', '.mp4', '.aac'):
      texts.extend(str(v) for v in audio.tags.get('\xa9lyr', []))
  ```
- **Reproduction / verification:** `wn27_probe3.py` section A/B — an MP3 with `USLT(encoding=3, lang="eng", desc="", text=["First line of lyrics", "Second line"])` yields `extract_embedded_lyrics(...) == "['First line of lyrics', 'Second line']"`; section C shows `str(MP4FreeForm(b"la la la")) == "b'la la la'"`.
- **Suggested fix:** unwrap the payloads per container (`USLT.text` → join, `MP4FreeForm` → decode) and strip only the repr artefacts, not the content.
- **Fix side effects:** the returned text changes shape for MP3/M4A; any consumer that currently parses the repr (none found) would need updating. `services/lyrics_lookup.py` only `.strip()`s the result, so it is unaffected.
- **Discovered by:** A

#### F-WN-27-5  [P2] — `purge_stream_cache` measures the quota over covers+temp+streams but only purges `streams/` → the whole stream cache is wiped while "used" never drops

- **File:** `utils/cache_manager.py:78-93` (`get_cache_size`), `utils/cache_manager.py:192-196`, `utils/cache_manager.py:221-250`
- **Confirmed:** yes
- **Description:** `total_used = self.get_cache_size(force_rescan=True)` sums **covers + streams + temp**, and the target is `0.75 * quota`. The eviction loop, however, only walks candidates from `self._streams_dir` and only subtracts the bytes it frees there. If `covers + temp` alone already exceed the 75 % target, the `break` condition `(total_used - freed_bytes) <= target_bytes` can never become true, so **every** cached stream is deleted on every purge — and the reported usage stays above the quota.
- **Cause:** the quota accounting and the eviction set use different directories; there is no purge path for the covers or temp directories except the explicit `clear_covers_cache()` / `clear_temp()` buttons.
- **Trigger conditions:** covers grow past ~75 % of the configured quota. The quota can be as low as the enforced 1 GB minimum (`core/api.py:4072-4074`), and covers are never pruned automatically — one 1 GB quota plus ~800 MB of embedded covers is enough.
- **User impact:** every prefetch (`utils/cache_manager.py:315` calls `self.purge_stream_cache()` before each download) and every quota change wipes the entire stream cache, so cached streams never survive; the storage panel keeps reporting the cache "over quota" and the user cannot tell why.
- **Evidence:**
  ```python
  # utils/cache_manager.py:85-89
  cache_dirs = [self._covers_dir, self._streams_dir, self._temp_dir]
  for c_dir in cache_dirs:
      for _, file_stat in self._cache_file_stats(c_dir):
          total += file_stat.st_size
  # utils/cache_manager.py:223 (candidates only from streams)
  for fp, file_stat in self._cache_file_stats(self._streams_dir):
  # utils/cache_manager.py:242-244
  for fp, _, size in candidates:
      if not force_all_temporary and (total_used - freed_bytes) <= target_bytes:
          break
  ```
- **Reproduction / verification:** `wn27_probe2.py` section D reproduces the protection logic against a real `CacheManager` instance (favourite track correctly protected). The accounting mismatch follows directly from the quoted lines: `total_used` includes `covers_dir`/`temp_dir` while `candidates` only contains `streams_dir` files.
- **Suggested fix:** compute the target against the *streams* portion (or add an eviction path for covers/temp), and keep the "used" number and the evicted set consistent.
- **Fix side effects:** purging covers automatically would delete artwork the user may still expect; a separate covers quota/LRU policy would be needed.
- **Discovered by:** A

#### F-WN-27-6  [P2] — Two implementations manage `~/.nedotify/streams` with different rules; the automatic one defeats the settings quota and leaves the DB inconsistent

- **File:** `utils/cache_manager.py:171-271` (`purge_stream_cache`), `core/api.py:3595-3638` (`_clean_stream_cache`), `core/api.py:3665-3671` (call site), `core/database.py:2142` (`set_cached_file` → `expires_at = NULL`), `core/database.py:2227-2242` (`cleanup_expired_cache`)
- **Confirmed:** yes
- **Description:** `CacheManager.purge_stream_cache` applies the **settings quota**, protects downloaded/favourite tracks and in-flight downloads, and synchronises the DB. `core/api.py::_clean_stream_cache` manages the same directory with a **hard-coded 350 MB / 48 h** policy, **no** favourite/download protection and **no** DB synchronisation — and it runs automatically from `prefetch_track` every ≥10 minutes (`core/api.py:3665-3671`, reached from `js/player.js:1441`).
  Consequences: (a) a user who raises the quota above 350 MB still has the stream cache pruned at 350 MB; (b) the cached file of a *favourite* track is deleted although `purge_stream_cache`'s documented contract says it is preserved; (c) `stream_cache.cached_file_path` keeps pointing at a deleted file, and because `set_cached_file` sets `expires_at = NULL` while `cleanup_expired_cache` skips every row that has a `cached_file_path`, **those stale rows are immortal** and are never reconciled.
- **Cause:** a second, independent eviction policy was added on the API side instead of delegating to the CacheManager.
- **Trigger conditions:** normal use — any track change that triggers a prefetch once every 10 minutes while the streams folder exceeds 350 MB or contains files older than 48 h.
- **User impact:** cached audio of favourite tracks disappears without warning, the configured quota is not honoured, and the DB keeps pointing at files that no longer exist. The stale pointer is currently masked by defensive `os.path.exists` checks in `core/offline.py:23`, `core/proxy.py:797` and `core/api.py:1536`, but `services/smart_playlists.py:159` uses the mere *presence* of `cached_file_path` in its SQL availability predicate (the follow-up `available_tracks()` filter re-checks existence, so no track is listed today). The residue is that the immortal stale rows accumulate and no component can tell a live cache entry from a dead one.
- **Evidence:**
  ```python
  # core/api.py:3595-3604
  def _clean_stream_cache(self, max_size_mb: int = 350, max_age_hours: int = 48):
      """Clean cached audio streams using LRU and TTL to prevent disk bloat."""
      ...
      streams_dir = getattr(self._core.cache, "_streams_dir", None) or ...
  # core/api.py:3616-3636  -- age + size eviction, no DB write anywhere in the function
  # core/api.py:3665-3671
  if prune:
      self._clean_stream_cache()
  # utils/cache_manager.py:174-177 (the other, conflicting policy)
  - Strictly preserves files where is_downloaded = 1 OR is_favorite = 1.
  ```
- **Reproduction / verification:** static — `_clean_stream_cache` (45 lines) contains no `self._core.db` call at all, whereas `purge_stream_cache` L252-267 does the `stream_cache`/`tracks` update inside one transaction. Reachability: `js/player.js:1441` → `prefetch_track` → `core/api.py:3671`.
- **Suggested fix:** delete `_clean_stream_cache` and let `prefetch_track` call `CacheManager.purge_stream_cache()` (which already implements TTL-free LRU + protection + DB sync); if a TTL is wanted, add it to the CacheManager as one policy.
- **Fix side effects:** `purge_stream_cache` has no TTL today, so adopting it as-is changes the eviction semantics (size-driven only); the `_clean_stream_cache` unit test (`tests/test_playback_startup_performance.py:57`) monkeypatches the method and would need updating.
- **Discovered by:** A (root cause on the WN-27 side; `_clean_stream_cache` itself is `core/api.py` → owned by **WN-10**. Not double-reported.)

#### F-WN-27-7  [P2] — `is_safe_media_url` performs an uncached, blocking DNS lookup on the playback/download hot path and fails closed on DNS errors

- **File:** `utils/url_safety.py:24-33`
- **Confirmed:** yes
- **Description:** `is_safe_media_url` calls `socket.getaddrinfo(parsed.hostname, parsed.port or None)` with **no timeout** and **no memoisation**, and returns `False` for any `OSError` (DNS failure, no network, resolver timeout). It is called on the playback path (`audio/engine.py:176`, `audio/engine.py:440`) and on the download path (`core/downloader.py:639`, `core/downloader.py:650`, `core/download_transfer.py:67`). The parallel implementation `core/api.py::_is_ssrf_safe_url` (L161-193) *does* memoise its DNS verdicts (`_ssrf_cache_put`, L157) — `is_safe_media_url` does not.
- **Cause:** a synchronous, unbounded, uncached name resolution inside a request path, with a fail-closed policy that treats "could not resolve" as "hostile".
- **Trigger conditions:** (a) a slow/unresponsive DNS resolver → every stream resolution stalls for the OS resolver timeout (seconds to tens of seconds) before the fallback path is even entered; (b) the machine is offline or the DNS server is down → the guard rejects a perfectly legitimate, already-resolved stream URL.
- **User impact:** playback falls back from the direct URL to a full provider search (slow, or no result at all) exactly when the network is flaky; in `audio/engine.py:176` the URL is dropped (`direct_id = ""`), so the track silently resolves to the wrong thing or to nothing.
- **Evidence:**
  ```python
  # utils/url_safety.py:24-33
  try:
      infos = socket.getaddrinfo(parsed.hostname, parsed.port or None)
  except (OSError, UnicodeError, ValueError):
      return False
  if not infos:
      return False
  ```
  vs. the memoised sibling in `core/api.py:157` → `_ssrf_cache_put(hostname, verdict)`.
- **Reproduction / verification:** static reading + `socket.getaddrinfo` semantics (no timeout argument is accepted by the call). To observe: block DNS (e.g. a firewall on port 53) and call `is_safe_media_url("https://rr3---sn-x.googlevideo.com/x.m4a")` — it blocks for the resolver timeout and returns `False`.
- **Suggested fix:** memoise the verdicts per host (as `core/api.py` does), bound the resolution with a short timeout / resolve through a cached resolver, and distinguish "resolution failed" from "resolved to a private address" (fail-open only for an already-validated, provider-issued URL).
- **Fix side effects:** a fail-open path would weaken the SSRF guard → the fix must keep the private-range rejection; a cache needs invalidation/TTL handling.
- **Discovered by:** A

#### F-WN-27-8  [P2] — The "artist - title" fallback splits on the *first* `" - "`, so a leading track number becomes the artist

- **File:** `utils/tag_parser.py:111-116`
- **Confirmed:** yes
- **Description:** when a file has no artist tag, `parse_tags` falls back to the file name and then splits it on the first `" - "`:
  ```python
  if " - " in result["title"]:
      parts = result["title"].split(" - ", 1)
      result["artist"] = parts[0].strip()
      result["title"] = parts[1].strip()
  ```
  A file named `03 - Never Gonna Give You Up.mp3` therefore yields **artist = `"03"`**, title = `"Never Gonna Give You Up"`. The same split is applied to a genuine `"Artist - Title"` name, so the heuristic cannot tell the two apart.
- **Cause:** an unconditional split with no "is the first token a track number?" test and no attempt to look for a *later* separator.
- **Trigger conditions:** any untagged (or artist-less) audio file whose name starts with a track number — the most common naming scheme for ripped/downloaded files. This is the exact path used by `FileScanner._import_file` (`utils/file_scanner.py:119-139`) and by the watchdog auto-import (`services/watchdog_service.py:122`).
- **User impact:** the library shows "03" as the artist for the whole album; the search/suggestion index (`utils/search_query.py:62-64` reads `artist` from `tracks`) is polluted with numbers, and the "artist" filter groups unrelated tracks together.
- **Evidence:** see the quoted code above.
- **Reproduction / verification:** `wn27_probe3.py` section D — `parse_tags("03 - Never Gonna Give You Up.mp3")` → `title='Never Gonna Give You Up'`, `artist='03'`; `parse_tags("01 - Artist Name - Song Title.mp3")` → `title='Artist Name - Song Title'`, `artist='01'`.
- **Suggested fix:** only apply the split when the left part is not a bare track number (`^\d{1,3}$`), and otherwise look for the *last* separator or skip the heuristic; keep "Unknown Artist" when nothing sensible can be derived.
- **Fix side effects:** existing library rows imported with the current heuristic keep their bogus artist until the user re-scans or edits them.
- **Discovered by:** A

#### F-WN-27-9  [P2] — The folder-scanning half of `FileScanner` is unreachable: no bridge method ever calls `scan_folder`, so the watchdog auto-import never activates

- **File:** `utils/file_scanner.py:58-109` (`scan_folder`), `utils/file_scanner.py:157-162` (`rescan_all_folders`), `core/api.py:3436-3459` (`open_local_file` — the only caller), `services/watchdog_service.py:104-116` (`_sync_folders`)
- **Confirmed:** yes
- **Description:** `FileScanner` exposes `scan_folder`, `rescan_all_folders`, `scan_files`, `cancel_scan`, `on_progress`, `on_complete` and `on_file_found`, but the only production call sites in the whole repo are `core/api.py:3449` (`scanner.scan_single_file`, from the "open local file" dialog) and `services/watchdog_service.py:122` (`scanner._import_file`). There is **no** bridge method and **no** JS reference for "scan a folder" (`grep -n "scan_folder|scanFolder|add_folder|rescan"` over `core/api.py` and `ui/web_new_v2/js/**` → no matches). Consequently `db.add_scan_folder()` is never called, the `scan_folders` table stays empty and `watchdog_service._sync_folders()` never watches anything.
- **Cause:** the module was written for a folder-import feature that was never exposed through the bridge.
- **Trigger conditions:** always — the feature is simply absent in the shipped app.
- **User impact:** the user cannot import a music *folder*; only individual files through the open dialog. The auto-import watcher is dead code that silently does nothing.
- **Evidence:**
  ```python
  # utils/file_scanner.py:157-162
  def rescan_all_folders(self):
      """Rescan all registered folders."""
      folders = self.db.get_scan_folders()
      for folder in folders:
          if folder.get("auto_scan"):
              self.scan_folder(folder["folder_path"])
  ```
  Repo-wide grep for `scan_folder` → only `utils/file_scanner.py` (definition + internal call). Grep for `scanner\.` in `core/` → only `core/api.py:3449`.
- **Suggested fix:** either expose a `scan_music_folder` bridge method (and wire the UI + the watchdog), or delete the unreachable half of the module so the dead surface is not mistaken for a working feature.
- **Fix side effects:** exposing it activates `os.walk` over user-chosen roots — the walk has no symlink following (safe), no hidden/system-directory skip and no depth limit, so a root such as `C:\` would traverse `$RECYCLE.BIN` and `System Volume Information` and re-import recycled copies of the user's audio. The walk also needs `onerror` handling so unreadable directories do not abort the scan.
- **Discovered by:** A (missing bridge method is `core/api.py` → **WN-07**; not double-reported)

#### F-WN-27-10  [P3] — The `HD` / `HQ` junk patterns corrupt ordinary titles and artist names

- **File:** `utils/tag_parser.py:93-106`
- **Confirmed:** yes
- **Description:** the cleanup list contains `r"(?i)HD"` and `r"(?i)HQ"` with **no word boundaries**, and they are applied to both the title and the artist. Any occurrence of the two letters inside a word is deleted: `"Ashdown"` → `"Asown"`, `"CHD"` → `"C"`, `"Sh HQ"` → `"Sh"`.
- **Cause:** unanchored, case-insensitive literal patterns applied to free-text metadata.
- **Trigger conditions:** any track whose title or artist contains "hd" or "hq" as a substring (band names, model names, sample-pack names).
- **User impact:** the imported title/artist is silently mangled and the original value is lost (the file on disk is untouched, so a re-scan re-applies the same mangling).
- **Evidence:**
  ```python
  # utils/tag_parser.py:100
  r"(?i)HD", r"(?i)HQ", r"(?i)\(lyrics?\)", r"(?i)\[lyrics?\]"
  # utils/tag_parser.py:103-106
  for pattern in junk_patterns:
      result["title"] = re.sub(pattern, "", result["title"]).strip()
      if result["artist"]:
          result["artist"] = re.sub(pattern, "", result["artist"]).strip()
  ```
- **Reproduction / verification:** `wn27_probe3.py` section F — `'Ashdown' -> 'Asown'`, `'CHD' -> 'C'`; 20 other realistic titles were unchanged.
- **Suggested fix:** require word boundaries / bracket context, e.g. `r"(?i)\bHD\b"` inside brackets only, and drop the bare `HD`/`HQ` patterns.
- **Fix side effects:** titles that legitimately carry a `[HD]` marker would keep it (desired); previously mangled rows must be re-imported.
- **Discovered by:** A

#### F-WN-27-11  [P3] — `_extract_cover` takes the first `APIC` frame regardless of its picture type and trusts the declared MIME

- **File:** `utils/tag_parser.py:161-167`, `utils/tag_parser.py:191-203`
- **Confirmed:** yes
- **Description:** the MP3 branch iterates all ID3 frames and returns the **first** key starting with `APIC`, without looking at `apic.type`. ID3 picture types are `3 = front cover`, `4 = back cover`, `8 = media (artist logo)`, etc.; a file whose first `APIC` is the back cover or an artist logo yields that image as "the cover". The MIME is taken from the frame's declared `apic.mime` — the bytes are never sniffed — so a mis-declared frame produces a file whose extension and content type disagree with the actual image.
- **Cause:** no picture-type selection and no content sniffing.
- **Trigger conditions:** MP3 files that carry more than one `APIC` frame, or a frame with a wrong MIME.
- **User impact:** the wrong image is shown as the album art; the proxy serves it with the extension-derived Content-Type (`core/proxy.py:118`), which a browser may refuse to decode.
- **Evidence:**
  ```python
  # utils/tag_parser.py:161-167
  if ext == '.mp3':
      try:
          tags = ID3(filepath)
          for key in tags:
              if key.startswith('APIC'):
                  apic = tags[key]
                  return apic.data, apic.mime
  ```
  (Contrast `write_tags` L296, which does set `type=3  # 3 is cover front` — the read path does not mirror it.)
- **Reproduction / verification:** static reading of the loop + mutagen's `APIC.type` semantics; the "first frame wins" behaviour is directly visible in the quoted code (no `apic.type` check anywhere in `_extract_cover`).
- **Suggested fix:** prefer `apic.type == 3` and fall back to the first frame; derive the extension from the sniffed magic bytes (`\x89PNG`, `\xff\xd8`, `RIFF....WEBP`) instead of the declared MIME.
- **Fix side effects:** files whose only `APIC` is a back cover would keep showing the back cover (no regression), but previously mis-detected covers change.
- **Discovered by:** A

#### F-WN-27-12  [P3] — No size limit on the embedded cover: it is fully materialised in RAM and written to the cache, and covers are never purged by the quota

- **File:** `utils/tag_parser.py:87` (load), `utils/tag_parser.py:156-208` (`_extract_cover`), `utils/tag_parser.py:211-234` (`save_cover_to_file`), `utils/cache_manager.py:85-89` (covers counted), `utils/cache_manager.py:221-223` (only streams purged)
- **Confirmed:** yes
- **Description:** `_extract_cover` returns the raw picture bytes with no upper bound; `parse_tags` therefore holds the whole image in memory, and `save_cover_to_file` writes it verbatim into `~/.nedotify/covers/`. Nothing prunes that directory automatically (`purge_stream_cache` only walks `streams_dir`; `clear_covers_cache()` is only reachable from the explicit "clear storage" button), while `get_cache_size` counts the covers against the quota.
- **Cause:** no size guard on untrusted embedded metadata, and no eviction policy for the covers directory.
- **Trigger conditions:** a file with a multi-megabyte embedded image (common with 2000s-era "high quality" rips); the scan then holds that image in RAM for the duration of the import.
- **User impact:** a single large cover inflates the reported cache size, makes the quota unreachable (see F-WN-27-5) and is re-downloaded by the UI on every cover render.
- **Evidence:**
  ```python
  # utils/tag_parser.py:166-167
  apic = tags[key]
  return apic.data, apic.mime
  # utils/tag_parser.py:230-231
  with open(filepath, 'wb') as f:
      f.write(cover_data)
  ```
- **Reproduction / verification:** static — no length check exists between `_extract_cover` and `save_cover_to_file`; `utils/tag_parser.py:87` assigns the bytes straight into the result dict.
- **Suggested fix:** cap the cover size (e.g. 5-10 MB) in `_extract_cover`/`save_cover_to_file`, and either downscale or store a thumbnail; add a covers eviction rule to the CacheManager.
- **Fix side effects:** an over-large but legitimate cover would be dropped; the UI should fall back to the provider's cover URL.
- **Discovered by:** A

#### F-WN-27-13  [P3] — `parse_tags` reports failures with `print()` instead of the logger, so the diagnostic never reaches `~/.nedotify/logs/app.log`

- **File:** `utils/tag_parser.py:88-89`
- **Confirmed:** yes (the "print crashes the app" variant was tested and **refuted** — see notes)
- **Description:** the only diagnostic in the module is `print(f"[TagParser] Error parsing {filepath}: {e}")`. The app's single log sink is the rotating file handler on `~/.nedotify/logs/app.log` (`main.py:99-108`); stdout is not captured anywhere. In the packaged build (`setup_pyinstaller.spec:104`, `console=False`) stdout is not visible to the user at all.
- **Cause:** a leftover debug print instead of `logging.getLogger(...).warning(...)`.
- **Trigger conditions:** every unreadable / corrupt / unsupported audio file during an import.
- **User impact:** the user gets no explanation for a file that was imported with fallback metadata, and support has nothing in the log to work with.
- **Evidence:**
  ```python
  # utils/tag_parser.py:88-89
  except Exception as e:
      print(f"[TagParser] Error parsing {filepath}: {e}")
  ```
- **Reproduction / verification:** `wn27_probe.py` section 3 — corrupt files print `[TagParser] Error parsing ...: can't sync to MPEG frame` to stdout while the function still returns a valid fallback dict. **Tested and refuted:** with `sys.stdout = None` (the windowed-build situation that `main.py:88-92` guards against) `print()` on CPython 3.14 does **not** raise — it is a silent no-op. So the failure is observability-only, not a crash.
- **Suggested fix:** use `logger = logging.getLogger("TagParser")` and `logger.warning("Error parsing %s: %s", filepath, e, exc_info=True)`.
- **Fix side effects:** the log volume grows with every unreadable file; consider `exc_info=True` only at debug level.
- **Discovered by:** A

#### F-WN-27-14  [P3] — `purge_stream_cache` matches the *raw* `source_id` against the *sanitised* file name, so the favourite protection silently fails for ids with non-allowlisted characters

- **File:** `utils/cache_manager.py:198-219` (protection set), `utils/cache_manager.py:221-234` (candidate matching), `utils/cache_manager.py:293-294` (file naming)
- **Confirmed:** yes
- **Description:** the cached file on disk is named `f"{source}_{safe_id}.{ext}"` with `safe_id = re.sub(r'[^a-zA-Z0-9_-]', '_', str(source_id))` (`utils/cache_manager.py:293`), but the protection set is built from the **unsanitised** id: `protected_sources.add(f"{src}_{src_id}".lower())` (`utils/cache_manager.py:213`). The match is a substring test against the sanitised base name (`utils/cache_manager.py:229`), so any id containing a character outside `[A-Za-z0-9_-]` (a dot, a slash, non-ASCII) makes the two strings differ and the protection does not apply.
- **Cause:** the same identifier is sanitised in one place and not in the other; the protection is a fuzzy substring match rather than a normalised path comparison.
- **Trigger conditions:** a provider whose `source_id` contains a `.` or a non-ASCII character, for a track that is a favourite or downloaded.
- **User impact:** the cached audio of a favourite track is deleted although `purge_stream_cache`'s docstring promises it is preserved ("Strictly preserves files where is_downloaded = 1 OR is_favorite = 1").
- **Evidence:**
  ```python
  # utils/cache_manager.py:213
  protected_sources.add(f"{src}_{src_id}".lower())
  # utils/cache_manager.py:225 / 229
  base_name = os.path.splitext(os.path.basename(fp))[0].lower()
  if any(p_src in base_name for p_src in protected_sources):
  ```
- **Reproduction / verification:** `wn27_probe2.py` section D — with `source_id = "abc.def"` the file on disk is `youtube_abc_def.mp3` while the protection key is `youtube_abc.def`; the substring test `p_src in base_name` evaluates to `False` (`p_src='youtube_abc.def' base_name='youtube_abc_def' protected=False`). With the realistic id `abc_def` it matches (`protected=True`).
- **Suggested fix:** build the protection key with the same sanitiser used for the file name (or compare normalised paths), and keep the raw id only for the DB lookup.
- **Fix side effects:** none; the sanitised key is exactly what is on disk.
- **Discovered by:** A

#### F-WN-27-15  [P3] — Three different cover-file naming conventions in `~/.nedotify/covers` for the same track

- **File:** `utils/tag_parser.py:226` (`cover_{track_id}{ext}`), `utils/cache_manager.py:430` (`cover_{track_id}{ext}`), `core/api.py:3954` (`{track_id}{cover_ext}`)
- **Confirmed:** yes
- **Description:** `save_cover_to_file` (used by the file scanner) and `CacheManager.save_cover_from_url` both write `cover_<id><ext>`, while `core/api.py::update_track_tags` writes `<id><ext>` into the **same** directory. A track that has both a locally extracted cover and a downloaded one therefore ends up with two or three files for the same artwork.
- **Cause:** three independent naming schemes for the same cache directory.
- **Trigger conditions:** any track that is both imported from disk and has a provider cover, or whose tags are edited after a cover download.
- **User impact:** the storage panel over-reports the cover cache; a stale copy survives a cover change and can be served by the proxy (`core/proxy.py:141-167` serves every image-extension file under the cover roots).
- **Evidence:**
  ```python
  # utils/tag_parser.py:226
  filename = f"cover_{track_id}{ext}"
  # utils/cache_manager.py:430
  filepath = os.path.join(self._covers_dir, f"cover_{track_id}{ext}")
  # core/api.py:3954
  cached_cover = os.path.join(covers_dir, f"{track_id}{cover_ext}")
  ```
- **Reproduction / verification:** static — the three literals are quoted above; the collision between the first two is exact (`cover_<id>.jpg`).
- **Suggested fix:** one naming scheme for the covers cache (e.g. `<id><ext>`) with the old names cleaned up on migration.
- **Fix side effects:** existing `cover_<id>.*` files become orphans and must be removed or migrated.
- **Discovered by:** A

#### F-WN-27-16  [P3] — `FileScanner._scanning` is a boolean, not a scan generation → `cancel_scan()` followed by a new `scan_folder()` aborts the new scan

- **File:** `utils/file_scanner.py:60-63`, `utils/file_scanner.py:85-87`, `utils/file_scanner.py:104-106`, `utils/file_scanner.py:164-167`
- **Confirmed:** yes
- **Description:** the scan thread's `finally` block unconditionally sets `self._scanning = False`:
  ```python
  finally:
      with self._scanning_lock:
          self._scanning = False
  ```
  `cancel_scan()` also sets the flag to `False`. If the user cancels and immediately starts a new scan, the new `scan_folder` sets the flag to `True` and starts a second thread; the *old* thread then finishes and its `finally` resets the flag to `False`, which terminates the **new** scan at its next file.
- **Cause:** a shared boolean is used as both "is a scan running" and "has this scan been cancelled"; there is no generation/ownership token.
- **Trigger conditions:** `cancel_scan()` immediately followed by `scan_folder()`.
- **User impact:** the new scan stops after a few files and `db.add_scan_folder()` / `update_scan_time()` are never reached, so the folder is not registered as scanned.
- **Evidence:** see the quoted code above (`utils/file_scanner.py:85-87` breaks the loop when `not self._scanning`; L104-106 clears the flag unconditionally).
- **Reproduction / verification:** static — the two writers of the flag (`cancel_scan` L166-167 and the `finally` L105-106) have no ownership check. **Note:** today this is unreachable in the shipped app because `scan_folder`/`cancel_scan` have no caller (F-WN-27-9); it becomes live as soon as the folder-import bridge method is added.
- **Suggested fix:** use a per-scan token (e.g. `self._scan_token = object()` captured by the thread) and only clear the flag if the finishing thread owns the current token.
- **Fix side effects:** none.
- **Discovered by:** A

---

### 3. Clean areas

- **`utils/search_query.py`** — read in full and verified: `_distance` is a correct **restricted Damerau–Levenshtein (OSA)** implementation with a sound cutoff. I compared it against a brute-force Levenshtein and against a reference OSA implementation over 18 000 random (string, ceiling) combinations: **0** mismatches against the OSA reference for the distance itself and **0** cutoff-contract violations (`got <= k` ⟺ `osa <= k`). The 93 differences against *plain* Levenshtein are the intended transposition tolerance ("cd" vs "dc" = 1 edit), not a bug. The early exit `if min(current) > ceiling` is sound, and `abs(len(left)-len(right)) > ceiling` short-circuits correctly. `suggest_search_queries` is bounded (query ≤ 120 chars, candidate ≤ 240 chars, ≤ 4000 candidates, ≤ 3 suggestions), the ranking (`sorted(matches)` by distance, then length delta) is sane, the empty/short/query-too-long cases return `[]`, the `ё`/`е` normalisation and the ЙЦУКЕН⇄QWERTY layout tables are positionally correct (33 ↔ 33 chars) and the `_TO_LATIN` reverse map is the exact inverse. The DB source is the `tracks` table (the library), indexed by `idx_tracks_added_at ON tracks(added_at DESC)` (`core/database.py:365`), so the `ORDER BY added_at DESC, id DESC LIMIT 600` query is index-backed. Measured cost with 600 synthetic tracks: **0.024 s**; the bridge method is only invoked after an empty search result (`ui/web_new_v2/js/search.js:1046-1055`), not per keystroke.
- **`utils/stream_urls.py::stream_url_expired`** — correct and deliberately conservative: only the `expire` / `Expires` parameters are interpreted (so `X-Amz-Expires` durations and other numeric parameters are not misread as timestamps), values must be all digits and ≥ 6 long, a 60 s margin is applied, and every malformed input falls through to `False` ("leave it to the provider's TTL"). Verified against 9 URL shapes (including `expire=abc`, `expire=123`, a fractional value and a URL with a second numeric parameter): every verdict matched the intended semantics. The callers (`core/api.py:1514/1521/1543/1617/1644/1685`, `core/resolver.py:127`, `core/playback_recovery.py:168`, `services/base_service.py:202/211`) all pass a string or `None` and handle `False` correctly.
- **`utils/url_safety.py::is_safe_media_url`** — the guard itself is *correct*: the scheme allowlist is `http`/`https`, the host is resolved and **every** resolved address must be public (`is_private`, `is_loopback`, `is_link_local`, `is_reserved`, `is_multicast`, `is_unspecified`), IPv6 scope suffixes are stripped, and DNS failures / unparsable hosts fail closed. `urlparse` raising `ValueError` (e.g. a bad port) is caught. No caller that needs the guard omits it: `core/api.py` and `core/proxy.py` both use `core/api.py::_is_ssrf_safe_url` (re-exported by `core/proxy.py:23-24`), and `is_safe_media_url` is used by `audio/engine.py:176/440`, `core/downloader.py:639/650` and `core/download_transfer.py:67`. The defect is the *uncached blocking resolution* (F-WN-27-7), not the check logic.
- **`utils/cache_manager.py::save_cover_from_url`** — correct and safe: only `http(s)` URLs, an SSRF check plus a per-hop redirect re-check, a temp file + `os.replace` (so a torn download can never be cached), an explicit empty-response check, and a cleanup of the temp file on every failure path. The extension is taken from a fixed allowlist (`.jpg/.jpeg/.png/.webp`) → **contract #8 is satisfied**: no user-derived characters reach the file name.
- **`utils/tag_parser.py::save_cover_to_file`** — contract #8 is satisfied: the file name is `cover_{track_id}{ext}` where `track_id` is an int and `ext` comes from a fixed `.jpg/.png/.webp` allowlist. No user-supplied text reaches the file name.
- **`utils/tag_parser.py::parse_tags` — robustness against broken input** — verified: a zero-length `.mp3`, a garbage `.mp3`, an empty `.flac` and a garbage `.flac` all return a well-formed fallback dict (title = file stem, artist = "Unknown Artist", duration 0.0) and **do not raise**; the exception is caught by the blanket `except Exception` at `utils/tag_parser.py:88`. `write_tags` likewise raises a controlled `RuntimeError` (after rolling the file back) instead of propagating a mutagen exception.
- **`utils/tag_parser.py::_get_tag`** — correct: with `MutagenFile(..., easy=True)` the values are lists, and the helper unwraps `str(val[0])`; a missing key returns the default (`None` for genre/date/tracknumber, the file-stem/"Unknown Artist" defaults for title/artist/album); `KeyError`/`IndexError`/`TypeError` are caught. Multi-valued frames keep their first value, which is the intended behaviour.
- **`utils/file_scanner.py` — the directory walk** — `os.walk(folder_path)` is used **without** `followlinks`, so a symlink pointing at an ancestor cannot cause infinite recursion; unreadable directories are ignored by `os.walk`'s default `onerror=None` rather than aborting the scan; the extension allowlist is derived from a single source of truth (`AUDIO_EXTENSIONS = frozenset(SUPPORTED_FORMATS) | {'.opus','.alac','.aiff'}`, `utils/file_scanner.py:16`) and `core/proxy.py:122-128` mirrors it explicitly.
- **`utils/cache_manager.py` — the executor lifecycle** — `core/app.py:574` shuts `cache._executor` down with `shutdown(wait=False, cancel_futures=True)`, so an in-flight yt-dlp stream download cannot block the app's exit.
- **`utils/cache_manager.py::purge_stream_cache` — the DB synchronisation** — correct when it runs: the deleted paths are applied to `stream_cache.cached_file_path` and to `tracks` inside a **single** transaction (`utils/cache_manager.py:252-267`), and the in-flight downloads are protected through `_active_downloads` under `_active_downloads_lock`.
- **`utils/cache_manager.py::download_audio_stream`** — correct hardening: the cached artefact is validated with `_require_audio_file()` before it is registered, `overwrites=True` prevents a leftover partial download from being mistaken for a good one, and the stream id is sanitised with `re.sub(r'[^a-zA-Z0-9_-]', '_', ...)` → **contract #8 respected**.

---

### 4. Coverage gaps

- **The packaged app was not executed** (forbidden by the brief). The claim "in the packaged build `sys.stdout` is `None`" is therefore inferred from `setup_pyinstaller.spec:104` (`console=False`) and `main.py:88-92` (the `except AttributeError` guard around `sys.stdout.reconfigure`); the *consequence* (that `print()` is a silent no-op) **was** verified directly on CPython 3.14.7, so F-WN-27-13 is limited to the observability loss.
- **No real-world media corpus was available.** The MP3 fixtures used were synthesised (a valid MPEG-1 Layer III frame stream); FLAC/Ogg/WMA/ADTS-AAC fixtures were not produced, so the FLAC and Ogg *write* paths of `write_tags` and the Ogg *read* path of `_extract_cover` were verified by source/mutagen semantics rather than by a round trip on a real file. F-WN-27-2 is nevertheless confirmed at the byte level (the FLAC picture block was constructed with `mutagen.flac.Picture` and shown to differ from the image bytes).
- **`core/api.py::_clean_stream_cache` was not executed** (it lives in WN-10 and needs a full `AppCore`); the finding rests on reading the complete 45-line body plus the confirmed call chain `js/player.js:1441 → prefetch_track → core/api.py:3671`.
- **The exact size of the "over quota because of covers" scenario (F-WN-27-5) was not reproduced end-to-end** — it requires a multi-GB covers directory. The accounting mismatch itself is confirmed by the quoted lines (`total_used` spans three directories, the candidate set spans one).
- **`utils/cache_manager.py::get_cache_size` holds `_size_cache_lock` across the whole recursive scan.** I judged this a latency nit rather than a finding, but I did not measure the scan cost against a realistic (10 k+ file) cache tree.
- **The frontend rendering of a broken OGG cover** (F-WN-27-2) was not observed in the WebView; the conclusion that the proxy serves the non-image bytes follows from `core/proxy.py:118` (`COVER_EXTENSIONS`) and the stored file name.
- **No test in `tests/` currently pins** the behaviours found here: there is no test for `write_tags` atomicity/rollback, none for `_extract_cover` per format, none for `extract_embedded_lyrics` output shape, and `tests/test_search_query_suggestions.py` only covers the happy path. `tests/test_media_guard_f3.py` covers `is_safe_media_url` but not its DNS-failure behaviour.
