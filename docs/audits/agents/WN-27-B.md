## AREA WN-27 — Utility modules — ROLE B

### 1. Scope reviewed

**Files opened in full (read, not skimmed):**

| File | Lines | Notes |
|---|---|---|
| `utils/cache_manager.py` | 1–453 | whole file |
| `utils/file_scanner.py` | 1–181 | whole file |
| `utils/search_query.py` | 1–101 | whole file |
| `utils/stream_urls.py` | 1–26 | whole file |
| `utils/tag_parser.py` | 1–398 | whole file |
| `utils/url_safety.py` | 1–37 | whole file |

**Callees traced into other areas (read for evidence, not reviewed as their area):**

- `core/api.py` L95–195 (`_is_ssrf_safe_url`, `_dns_resolves_to_public_ip`, the SSRF memo), L3436–3459 (`open_local_file`), L3595–3638 (`_clean_stream_cache`), L3640–3683 (`prefetch_track`), L3910–4000 (`update_track_tags`), L4031–4090 (`set_cache_quota`), L4219–4221 (`get_search_suggestions`)
- `core/database.py` L146–205 (`_write_lock`, thread-local connection), L213–241 (`tracks` schema, `file_path TEXT UNIQUE`), L1054–1164 (`add_track`), L1172–1176 (`get_track_by_path`), L2136–2145 (`set_cached_file`), L2227–2242 (`cleanup_expired_cache`)
- `core/app.py` L150–209 (cache-cleanup loop), L296–379 (`re_resolve_stream_url_async` → `download_audio_stream`)
- `core/downloader.py` L629–662, `core/download_transfer.py` L55–84, `audio/engine.py` L160–219, L425–464 (the `is_safe_media_url` call sites)
- `core/proxy.py` L23–24, L131–220 (`_cover_roots`, `_resolve_inside_roots`), L797–798 (cached stream serving)
- `services/smart_playlists.py` L156–162 (`available_only` predicate), `services/watchdog_service.py` L104–129 (`_import_file` caller), `services/lyrics_lookup.py` L321–322
- `main.py` L145–229 (the global `socket.getaddrinfo` DoH patch), `setup_pyinstaller.spec` L97–104 (`console=False`)
- Installed `mutagen` 1.48.1 in `.venv_win`: `mutagen/_file.py` L209–304 (`File()`), `mutagen/_util.py` L527 (`__len__`), L767–836 (`insert_bytes`/`delete_bytes`/`resize_bytes`), `mutagen/id3/_file.py` L224–286 (`ID3.save`), `mutagen/flac.py` L839–893 (`FLAC._save`)

**Tests read:** `tests/test_cache_lru.py` (222 L), `tests/test_cache_performance.py` (131 L), `tests/test_proxy_paths.py`, `tests/test_proxy_ranges.py`, `tests/test_proxy_url_validation.py` (172 L), `tests/test_media_guard_f3.py` (313 L)

**Empirical verification:** 6 scratch probes under `%TEMP%\opencode\` (`wn27_probe.py` … `wn27_probe6.py`), run with `& ".venv_win\Scripts\python.exe"`. No file in the repository was modified; all scratch output is under `%TEMP%`.

---

### 2. Findings

#### F-WN-27-1  [P1] — `write_tags` mutates the user's audio file **in place**; the "writes atomically" docstring is false and a kill mid-write destroys the file
- **File:** `utils/tag_parser.py:237-397` (docstring at `:249`, backup at `:265-267`, in-place saves at `:302` / `:326` / `:347` / `:370` / `:386`); mutagen `id3/_file.py:268-273`, `flac.py:879-882`, `_util.py:767-836`
- **Confirmed:** yes
- **Description:** `write_tags` is the only code in the app that rewrites the user's own audio files. It claims to be atomic but performs **no** temp-file + `os.replace()` cycle: it copies the original to `%TEMP%\aura_tag_backup_*` and then lets mutagen rewrite the original file object in place. mutagen's ID3 path does `insert_bytes()`/`delete_bytes()` (which shift the whole tail of the file) followed by `f.write(data)`; the FLAC path does `resize_bytes()` then `f.write(b"fLaC")` + `f.write(data)` — i.e. the container header and the metadata region are overwritten before the audio frames.
- **Cause:** the author treated "copy the original aside, then call `mutagen.save()`" as an atomic transaction. It is only a *recoverable* transaction, and only while the Python process is alive and the exception is caught.
- **Trigger conditions:** the process is killed (crash, task-manager kill, power loss, OOM) between mutagen's first and last write; or the `except` block's `shutil.copy2(backup_path, filepath)` itself fails (disk full — the backup is a *full* copy of the file, so a nearly-full disk can make the rollback fail too).
- **User impact:** a truncated FLAC / MP3 with a half-written ID3 header — the file no longer parses (`mutagen` refuses it: "error"), the library entry loses its metadata, and for FLAC the STREAMINFO/audio offset can be destroyed, i.e. **lost music**. Additionally the `%TEMP%` backup is orphaned forever (nothing in the repo reaps `aura_tag_backup_*`: the only other hit is `tests/test_build_and_brand.py:294`), so every killed edit leaks a full copy of the audio file into `%TEMP%`.
- **Evidence:**
  ```python
  # utils/tag_parser.py:249-250
  Safely write physical ID3v2/Vorbis/MP4 tags to an audio file using mutagen.
  Checks write permissions, embeds cover art, and writes atomically.
  ...
  # utils/tag_parser.py:265-267  (a COPY, not a same-directory temp file)
  backup_fd, backup_path = tempfile.mkstemp(prefix="aura_tag_backup_", suffix=os.path.splitext(filepath)[1])
  os.close(backup_fd)
  shutil.copy2(filepath, backup_path)
  ...
  # utils/tag_parser.py:302
  tags.save(filepath, v2_version=3)          # mutagen writes INTO filepath
  ```
  ```python
  # .venv_win/Lib/site-packages/mutagen/id3/_file.py:268-273
  if (old_size < new_size):
      insert_bytes(f, new_size - old_size, old_size)     # shifts the file tail in place
  elif (old_size > new_size):
      delete_bytes(f, old_size - new_size, new_size)
  f.seek(0)
  f.write(data)
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wn27_probe.py` — after `write_tags(mp3, title="New Title")` the probe printed `same file object (no os.replace)? True   size 4106 -> 5202` (the inode is unchanged → the original file was rewritten, not replaced). The second block of the same probe emulates a crash between mutagen's header write and its frame write (writing only the first 20 bytes of the prepared ID3 block) and mutagen then fails to parse the file at all: `truncated tag -> error`. The mutagen source above shows the FLAC path is the same shape (`resize_bytes` + `f.write(b"fLaC")`).
- **Suggested fix:** write the mutated file to a temp file **in the same directory** and `os.replace()` it over the original (atomic on NTFS); keep the `%TEMP%` copy only as a belt-and-braces fallback; reap `aura_tag_backup_*` at startup.
- **Fix side effects:** `os.replace` across a volume boundary is not atomic → the temp file must live next to the original; the directory must be writable (it already must be); the file's ACL/alternate streams are replaced by the new inode (a `copy2`-then-replace keeps the timestamps, `os.replace` does not).
- **Discovered by:** B

---

#### F-WN-27-2  [P1] — `FileScanner._import_file` overwrites an **existing** track's cover with the new file's cover and silently drops the file, because `db.add_track()` can return a different track id
- **File:** `utils/file_scanner.py:111-152` (esp. `:128` and `:142-151`); root cause in `core/database.py:1112-1127` (`TRACK_IDENTITY_SQL = "LOWER(title) = LOWER(?) AND LOWER(artist) = LOWER(?)"`, `core/database.py:82`)
- **Confirmed:** yes
- **Description:** `_import_file` treats the return value of `db.add_track(...)` as "the id of the row I just created for *this file*". But `add_track` first looks for an existing row with the same **title+artist** (album/source/file are ignored) and returns *that* row's id. The code then writes the new file's embedded cover to `cover_<that id>.<ext>` and points the row's `cover_path` at it.
- **Cause:** `add_track`'s contract ("give me the id of this track, merging duplicates") is used as if it were "insert this file as a new row". The caller never verifies that the returned id belongs to the file it just parsed.
- **Trigger conditions:** any library that contains two files with the same title+artist (the same song in two formats, a single vs. an album version, a local file whose title+artist match a **cloud** track already in the DB).
- **User impact:** (a) the first track's cover is **destroyed** and replaced by the second file's cover; (b) the second file never enters the library at all (its `file_path` is not stored because the merged row already has one); (c) a cloud track row is silently mutated into a "downloaded local" row (`is_downloaded = 1` is set by `add_track` on the merge branch, `core/database.py:1087-1091` / `:1123-1126`).
- **Evidence:**
  ```python
  # utils/file_scanner.py:128-151
  track_id = self.db.add_track(
      title=tags["title"], artist=tags["artist"], album=tags["album"], ...
      file_path=filepath, source="local", ...)
  if tags.get("cover_data"):
      cover_path = save_cover_to_file(tags["cover_data"], tags["cover_mime"], self._covers_dir, track_id)
      if cover_path:
          self.db.conn.execute("UPDATE tracks SET cover_path = ? WHERE id = ?", (cover_path, track_id))
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wn27_probe4.py` (section A) — a `DatabaseManager` with a pre-existing cloud track `youtube/abc123` titled "Childhood" by "Radiohead"; importing local `a.mp3` then `b.mp3` with the same title+artist and a distinguishable cover payload produced:
  ```
  after importing a.mp3:  row id: 1  file_path: ...\a.mp3  is_downloaded: 1  cover_path: ...\covers\cover_1.jpg
  after importing b.mp3:  file_path: ...\a.mp3 (still the FIRST file)
                          -> the second file's cover replaced the first file's cover: True
  ```
- **Suggested fix:** after `add_track`, re-read the row (`db.get_track_by_path(filepath)`); only write the cover when the row's `file_path` is this file; make the cover file name derive from the file path (hash) instead of the row id.
- **Fix side effects:** de-duplicating by title+artist is deliberate (`core/database.py:1100-1111`) — the fix must not force a second row where the product intends one, only stop the cover from being clobbered.
- **Discovered by:** B (the id-merge itself belongs to WN-12, `core/database.py`)

---

#### F-WN-27-3  [P2] — The stream cache has **three** owners with divergent roots, expiry rules and protection rules; `AppApi._clean_stream_cache` deletes favourites' cached audio and leaves dangling DB rows
- **File:** `utils/cache_manager.py:171-271` (`purge_stream_cache`) vs `core/api.py:3595-3638` (`_clean_stream_cache`) vs `core/database.py:2227-2242` (`cleanup_expired_cache`); DB sync gap at `core/database.py:2142`; consumer `services/smart_playlists.py:159`
- **Confirmed:** yes
- **Description:** the same directory (`~/.nedotify/streams`) is garbage-collected by three independent implementations:

| | root / scan | size rule | age rule | protects favourites / downloads / in-flight | syncs the DB |
|---|---|---|---|---|---|
| `CacheManager.purge_stream_cache` (`utils/cache_manager.py:171`) | recursive (`_cache_file_stats`) | settings quota `storage.cache_quota_gb` (default 5 GB), target 75 % | none (LRU-by-mtime) | **yes** (favourite/downloaded + `_active_downloads`) | yes → `stream_cache.cached_file_path = NULL`, `tracks.is_cached = 0` |
| `AppApi._clean_stream_cache` (`core/api.py:3595`) | top level only (`os.scandir`) | hard-coded 350 MB, target 70 % | 48 h mtime | **no** | **no** |
| `db.cleanup_expired_cache` (`core/database.py:2227`) | n/a (rows only) | n/a | `expires_at < now` | n/a | deletes rows **only when `cached_file_path` is NULL/''** |

- **Cause:** no single component owns the stream cache; three modules each invented a policy. `core/api.py` hard-codes a 350 MB ceiling that contradicts the settings quota (5 GB) the UI exposes, and it has no notion of "protected".
- **Trigger conditions:** any stream cache older than 48 h, or a cache above 350 MB (i.e. the normal case on a real library) — `_clean_stream_cache` runs every 600 s from `prefetch_track` (`core/api.py:3667-3671`).
- **User impact:** the cached audio of a **favourite** or **downloaded** track is silently deleted; the DB keeps pointing at the deleted file (`stream_cache.cached_file_path` is never nulled), so the row lives forever (`set_cached_file` sets `expires_at = NULL`, `core/database.py:2142`, and `cleanup_expired_cache` only deletes rows *without* a cached path) and every consumer that trusts the path is wrong — `services/smart_playlists.py:159` counts the track as "has a local file" and offers it in an "available offline" smart playlist although the file is gone.
- **Evidence:**
  ```python
  # core/api.py:3616-3624  -- no protection at all, no DB sync
  for path, mtime, size in files:
      if (now - mtime) > max_age_sec:
          try:
              os.remove(path)
              total_size -= size
          except Exception:
              kept_files.append((path, mtime, size))
  ```
  ```python
  # core/database.py:2234-2238
  "DELETE FROM stream_cache WHERE expires_at IS NOT NULL "
  "AND datetime(expires_at) < datetime('now') "
  "AND (cached_file_path IS NULL OR cached_file_path = '')"
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wn27_probe4.py` (section B) — a favourite track (`youtube/abc123`) whose cached file `streams/youtube_abc123.m4a` was back-dated 72 h:
  ```
  CacheManager.purge_stream_cache(force_all_temporary=True) freed: 0 | favourite file still there: True
  AppApi._clean_stream_cache -> favourite file still there: False
  DB cached_file_path after _clean_stream_cache: ...\streams\youtube_abc123.m4a
  -> dangling DB path pointing at a deleted file: True
  db.cleanup_expired_cache() deleted rows: 0 | row still present: True
  expires_at for a row with a cached file: None
  smart_playlists 'has file' predicate sees a row with cached_file_path: 1
  ```
- **Suggested fix:** make `CacheManager` the single owner; delete `AppApi._clean_stream_cache` and have `prefetch_track` call `cache.purge_stream_cache()`; make `cleanup_expired_cache` also clear rows whose `cached_file_path` no longer exists on disk.
- **Fix side effects:** `_clean_stream_cache`'s 350 MB ceiling currently bounds the disk usage far below the 5 GB the settings UI promises; removing it changes when the disk is reclaimed (the quota-driven purge is the user-visible contract). Windows `os.remove` on a file the proxy has open fails with `PermissionError` (caught) — that behaviour is preserved either way.
- **Discovered by:** B (the *behaviour* of `_clean_stream_cache` belongs to WN-10, `core/api.py` L3595–4228; the ownership fragmentation is WN-27)

---

#### F-WN-27-4  [P2] — `parse_tags` treats "this file has no tags" as "this is not an audio file": untagged files lose duration, bitrate and sample rate
- **File:** `utils/tag_parser.py:61-62` (`if audio:`), mutagen `mutagen/_util.py:527` (`def __len__(self): return len(self.keys())`)
- **Confirmed:** yes
- **Description:** `parse_tags` guards the whole metadata extraction with `if audio:`. mutagen's `FileType` inherits `DictMixin.__len__`, which returns the **number of tags**, so an audio file with zero tags is *falsy* and the entire block (duration, bitrate, sample_rate, title, artist, album, genre, year, track number) is skipped.
- **Cause:** truthiness of a mapping-like object was used as an "is this a readable audio file?" test.
- **Trigger conditions:** any file without tags — a plain WAV, a freshly converted FLAC/OGG, an MP3 with no ID3v2 header. This is the normal case for WAV.
- **User impact:** the track is imported with `duration = 0.0`, `bitrate = 0`, `sample_rate = 0` → the library shows "0:00", progress bars are broken, and duration-based sorting/smart playlists mis-rank it.
- **Evidence:**
  ```python
  # utils/tag_parser.py:61-66
  audio = MutagenFile(filepath, easy=True)
  if audio:                              # False when the file has ZERO tags
      if hasattr(audio, 'info') and audio.info:
          result["duration"] = getattr(audio.info, 'length', 0.0)
  ```
  ```python
  # .venv_win/Lib/site-packages/mutagen/_util.py:527-528
  def __len__(self):
      return len(self.keys())
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wn27_probe6.py` — a 1.9 MB WAV fixture: `MutagenFile(w, easy=True).info.length` = `120.0` and `bool(info)` = `True`, yet `parse_tags(w)` returns `duration: 0.0`. The same WAV after a valid ID3 tag was appended returns `duration: 120.0` — proving the branch is skipped purely because the tag count was 0.
- **Suggested fix:** test `if audio is not None:` (and read `audio.info` independently of the tag dict); the cover extraction at `:87` is already outside the branch and should stay there.
- **Fix side effects:** files that are not audio at all (e.g. a renamed `.mp3`) will now produce `duration = 0.0` from a broken header instead of the filename default — the `try/except` at `:88` already covers the exception path.
- **Discovered by:** B

---

#### F-WN-27-5  [P2] — WAV (and WMA) support is advertised but the metadata is never read and the tags can never be written
- **File:** `utils/tag_parser.py:23` (`SUPPORTED_FORMATS` includes `.wav`/`.wma`), `:61` (`easy=True`), `:145-153` (`_get_tag` asks for `'title'`/`'artist'`), `:372-386` (the `else` write branch); UI filter `core/api.py:3441`
- **Confirmed:** yes
- **Description:** mutagen's `easy=True` mode only provides normalised keys for `EasyMP3`, `EasyMP4` and `EasyTrueAudio`. A `.wav` is opened as a raw `WAVE` object whose tag dict is an **ID3 frame dict** (`TIT2`, `TPE1`), and a `.wma` is opened as a raw `ASF` object whose key is `'Title'`. `_get_tag` asks for `'title'`/`'artist'`, which those containers do not have, so the lookup always misses and the defaults (filename / "Unknown Artist") are used. The write path is equally broken: the `else` branch assigns a **list of strings** to the tag dict of a `WAVE`/`ASF` object, which mutagen rejects.
- **Cause:** one generic "easy" accessor was assumed to cover every format in `SUPPORTED_FORMATS`.
- **Trigger conditions:** importing or tagging any WAV/WMA file. The file dialog explicitly offers `*.wav` (`core/api.py:3441`).
- **User impact:** WAV files enter the library with no title, no artist and no album (the filename is the title); the tag editor refuses them with a raw Russian `RuntimeError` ("Ошибка при записи тегов в файл: ['New Title'] not a Frame instance").
- **Evidence:**
  ```python
  # utils/tag_parser.py:145-153
  def _get_tag(audio, key: str, default=None):
      try:
          val = audio.get(key)          # 'title' / 'artist' / 'album'
  ```
  ```python
  # utils/tag_parser.py:372-386  (fallback branch for .wav / .wma)
  audio = MutagenFile(filepath, easy=True)
  if audio is not None:
      if title is not None:
          audio['title'] = [str(title)]     # WAVE/ASF have no such key
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wn27_probe6.py` — a WAV carrying a genuine ID3 tag (`{'TIT2': ... 'Real Title', 'TPE1': ... 'Real Artist'}`) gives `parse_tags -> {'title': 'tagged', 'artist': 'Unknown Artist', ...}` (i.e. the *filename* and the placeholder), and `write_tags(w2, title="New Title")` raises `RuntimeError … ['New Title'] not a Frame instance`. A WAV whose first bytes are an ID3 header is additionally mis-detected by mutagen as MP3 → `can't sync to MPEG frame` (`%TEMP%\opencode\wn27_probe5.py`).
- **Suggested fix:** add a format-specific tag accessor (ID3 frames `TIT2/TPE1/TALB/TCON` for WAV, ASF `'Title'/'Author'` for WMA) and a WAV/ASF write branch, or drop `.wav`/`.wma` from `SUPPORTED_FORMATS` and from the dialog filter so the product does not promise what it cannot deliver.
- **Fix side effects:** adding WAV support changes every existing WAV row's title/artist on the next rescan (an improvement, but a visible library diff).
- **Discovered by:** B

---

#### F-WN-27-6  [P2] — `write_tags` embeds the cover and the tag values without any size limit; the caller reads the whole cover file into RAM
- **File:** `utils/tag_parser.py:290-300` (MP3 APIC), `:317-324` (FLAC picture), `:341-345` (MP4 covr), `:362-368` (OGG picture); amplifying caller `core/api.py:3939-3940`
- **Confirmed:** yes
- **Description:** neither the tag strings nor `cover_bytes` are bounded. `cover_bytes` is written verbatim into the container. The bridge caller loads the chosen file completely into memory first (`cf.read()`), and the file dialog it uses also offers "All files (*.*)", so the "cover" can be any file at all.
- **Cause:** no size policy at the embed site, and the read is unbounded at the call site.
- **Trigger conditions:** the user picks a large file as the cover, or pastes a very long title.
- **User impact:** the audio file grows by the size of the embedded payload (measured: a 200 000-character title grew a 4 KB MP3 to 405 KB); the process holds the whole payload in RAM; because the write is not atomic (F-WN-27-1), a larger payload widens the window in which a kill corrupts the file.
- **Evidence:**
  ```python
  # utils/tag_parser.py:290-300
  if cover_bytes:
      tags.setall('APIC', [APIC(encoding=3, mime=cover_mime or 'image/jpeg', type=3, desc='Cover', data=cover_bytes)])
  ```
  ```python
  # core/api.py:3939-3940  (the unbounded read that feeds it)
  with open(new_cover_path, "rb") as cf:
      cover_bytes = cf.read()
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wn27_probe.py` — `write_tags(mp3c, title="X" * 200000)` → `huge title ok, size -> 405149` (from 4 106 bytes).
- **Suggested fix:** cap the cover at a sane maximum (e.g. 2–5 MB) and the tag strings at a few hundred characters, reject with a user-facing message instead of silently embedding; read the cover with a bounded read.
- **Fix side effects:** the cap must not break the existing "embed the whole album art" behaviour for very large PNGs; the caller-side cap belongs to WN-07 (`core/api.py`).
- **Discovered by:** B (the unbounded `cf.read()` is WN-07's; the unbounded embed is WN-27's)

---

#### F-WN-27-7  [P2] — `utils/url_safety.py` is **not** the SSRF policy of the app: `core/api.py` and `core/proxy.py` use a second, divergent implementation that fails **open** on DNS errors
- **File:** `utils/url_safety.py:13-37`; the parallel copy at `core/api.py:133-195` (imported by the proxy at `core/proxy.py:23-24`)
- **Confirmed:** yes
- **Description:** `grep` for `is_safe_media_url` over the whole repo yields exactly four production call sites — `core/downloader.py:639`, `core/downloader.py:650`, `core/download_transfer.py:67`, `audio/engine.py:176`, `audio/engine.py:440`. **`core/api.py` and `core/proxy.py` never call it.** The proxy — the component that actually issues outbound requests — imports `_is_ssrf_safe_url` from `core/api.py`, which is a *different* implementation with different semantics: `utils/url_safety.py` fails **closed** on a DNS error (`except (OSError, UnicodeError, ValueError): return False`), while `core/api.py:143-155` starts from `verdict = True` and, when `socket.getaddrinfo` raises, only downgrades the verdict for four literal prefixes (`169.254.`, `10.`, `192.168.`, `127.`) — every other unresolvable host is classified **safe**.
- **Cause:** the module that looks like the single source of truth for URL safety was never adopted by the two highest-risk sinks; the copy inside `core/api.py` predates it and has the opposite failure mode.
- **Trigger conditions:** any URL whose hostname does not resolve (typo, offline, blocked DNS) passed through `_is_ssrf_safe_url`.
- **User impact:** the security posture of the app is decided by the *weaker* of two policies. A host that fails to resolve is treated as safe by the proxy path but as unsafe by the download path, so identical URLs are accepted or rejected depending on which code path handles them.
- **Evidence:**
  ```python
  # utils/url_safety.py:24-29   -- fails CLOSED
  try:
      infos = socket.getaddrinfo(parsed.hostname, parsed.port or None)
  except (OSError, UnicodeError, ValueError):
      return False
  ```
  ```python
  # core/api.py:143-155   -- fails OPEN
  verdict = True
  try:
      addr_info = socket.getaddrinfo(hostname, None)
      ...
  except Exception:
      # If DNS resolution fails, fallback string check
      if hostname.startswith("169.254.") or hostname.startswith("10.") or \
         hostname.startswith("192.168.") or hostname.startswith("127."):
          verdict = False
  ```
  ```python
  # core/proxy.py:23-24
  from core.api import _is_ssrf_safe_url
  _is_safe_url = _is_ssrf_safe_url
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wn27_probe.py` section B — `is_safe_media_url` correctly rejects `http://2130706433/`, `http://0x7f000001/`, `http://017700000001/`, `http://[::1]/`, `http://[::ffff:127.0.0.1]/`, `file:///C:/Windows/win.ini`, `javascript:`, `data:`, `\\server\share`, `169.254.169.254`, `10.x`, `192.168.x`, `[fe80::1]`, `0.0.0.0`, `user:pass@127.0.0.1` and every DNS failure, and accepts a public literal. So `utils/url_safety.py` itself is sound; the defect is that it is bypassed. The fail-open behaviour of the copy is visible in the source quoted above.
- **Suggested fix:** make `utils/url_safety.py` the only implementation; have `core/api.py::_is_ssrf_safe_url` delegate to it (keeping the 120 s memo) and let `core/proxy.py` import from `utils`; give both the same fail-closed semantics.
- **Fix side effects:** the proxy's memoisation and the "safe redirect handler" in `utils/cache_manager.py:416-421` depend on the current API; fail-closed would block requests to hosts whose DNS is momentarily broken — that is the intended trade-off and already the behaviour of the download path.
- **Discovered by:** B (the fail-open copy itself is WN-03/WN-11's defect; the duplication is WN-27's)

---

#### F-WN-27-8  [P2] — `is_safe_media_url` performs an unmemoised, blocking DNS lookup on the playback and download hot paths (and the check is not pinned to the connection → DNS-rebinding window)
- **File:** `utils/url_safety.py:25`; call sites `audio/engine.py:176`, `audio/engine.py:440`, `core/downloader.py:639`, `core/downloader.py:650`, `core/download_transfer.py:67`
- **Confirmed:** yes (blocking cost and the absence of memoisation are confirmed by reading; the rebinding window is a hypothesis about exploitability, not a demonstrated bypass)
- **Description:** every call performs a fresh `socket.getaddrinfo`. `main.py:225` replaces `socket.getaddrinfo` globally with a DoH fallback that, when the OS resolver fails, tries three DoH endpoints at 2 s each (`main.py:200-221`) — i.e. up to ~6 s *per call*, plus the OS resolver timeout. The sibling implementation in `core/api.py:99-131` memoises exactly this verdict for 120 s (and `core/api.py:95-98` documents the 6 s stall as the reason). `utils/url_safety.py` has no memo and no timeout. `core/download_transfer.py:67` re-checks on **every redirect hop** (up to 6 hops).
- **Cause:** the check was written as a pure function without the caching/latency characteristics the codebase already knows it needs.
- **Trigger conditions:** the blocked-DNS scenario the DoH fallback exists for; or any machine with a slow resolver. For SoundCloud the check runs on **every** resolution, because `audio/engine.py:440` always builds an `https://soundcloud.com/...` target.
- **User impact:** slow or failed track resolution and download starts; a download with several redirects pays the lookup several times. Because the verdict is not bound to the IP the request actually connects to (a second, independent resolution happens inside `requests`/`yt-dlp`), a host that answers with a public address during the check and a private one during the request passes the guard — the classic DNS-rebinding TOCTOU.
- **Evidence:**
  ```python
  # utils/url_safety.py:24-27
  try:
      infos = socket.getaddrinfo(parsed.hostname, parsed.port or None)
  except (OSError, UnicodeError, ValueError):
      return False
  ```
  ```python
  # core/api.py:95-101 (the memo the other implementation has)
  # main.py patches socket.getaddrinfo with a DoH fallback over 3 endpoints at 2s each, so
  # a single unresolvable host could block a proxy thread for ~6s ...
  _SSRF_CACHE_TTL = 120.0
  _SSRF_CACHE_MAX = 512
  ```
  ```python
  # core/download_transfer.py:64-78 (the check per redirect hop)
  for redirect_count in range(6):
      self.checkpoint()
      if not is_safe_media_url(url):
          raise ValueError('Unsafe media URL rejected')
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wn27_probe.py` section B — every rejected URL takes a live `getaddrinfo` call; the module has no cache attribute and no timeout parameter. To observe the blocking cost, run the app with a blackholed DNS server and resolve one SoundCloud track: `audio/engine.py:440` blocks for the OS resolver timeout (plus the DoH fallback), whereas the same hostname checked through `core/api.py::_is_ssrf_safe_url` returns from the 120 s memo.
- **Suggested fix:** add the same bounded memo (host → verdict, TTL, max entries) to `utils/url_safety.py` and use it from both implementations; consider resolving once and pinning the IP for the connection.
- **Fix side effects:** a memoised negative verdict delays the retry after a DNS outage by up to the TTL; the memo must be invalidated when `main.py` re-installs the DoH patch.
- **Discovered by:** B

---

#### F-WN-27-9  [P2] — The purge's "protect my favourites" key is built from the **raw** source id while the cached file name uses the **sanitised** id → a favourite's cached stream can be purged
- **File:** `utils/cache_manager.py:213` vs `:293` vs `:229-232`
- **Confirmed:** yes
- **Description:** `purge_stream_cache` builds `protected_sources = {f"{src}_{src_id}".lower()}` from the **raw** database `source_id`, but the file on disk is named from `safe_id = re.sub(r'[^a-zA-Z0-9_-]', '_', str(source_id))`. The protection test is a substring match (`any(p_src in base_name ...)`). For any `source_id` containing a character outside `[A-Za-z0-9_-]` the two strings differ and the protection never matches.
- **Cause:** two different normalisations of the same identifier are used to build and to look up the key.
- **Trigger conditions:** a provider whose ids contain e.g. `.`, `:`, `/` or non-ASCII characters; the favourite's cached stream is then deleted even though the code intends to protect it. The same substring test also *over*-protects: `source_id = "a"` protects every cached file whose name contains `youtube_a`.
- **User impact:** a favourite's cached audio is purged (it has to be re-downloaded) even though the module documents "Strictly preserves files where is_downloaded = 1 OR is_favorite = 1".
- **Evidence:**
  ```python
  # utils/cache_manager.py:293-294  (the file name)
  safe_id = re.sub(r'[^a-zA-Z0-9_-]', '_', str(source_id))
  download_id = f"{source}_{safe_id}"
  ...
  # utils/cache_manager.py:210-213  (the protection key)
  src = row[1]; src_id = row[2]
  if src and src_id:
      protected_sources.add(f"{src}_{src_id}".lower())
  ...
  # utils/cache_manager.py:229-231  (the lookup)
  if any(p_src in base_name for p_src in protected_sources):
      continue
  ```
- **Reproduction / verification:** the two code paths are side by side at `utils/cache_manager.py:213` vs `:293`; a one-line demonstration: `re.sub(r'[^a-zA-Z0-9_-]', '_', 'a.b')` → `'a_b'` ≠ `'a.b'`, so the key `"youtube_a.b"` can never be a substring of the basename `"youtube_a_b"`. In practice the current provider ids are alphanumeric, so the defect is latent rather than routinely triggered.
- **Suggested fix:** derive both the key and the file name from the same `safe_id` normalisation, and compare exact ids rather than substrings.
- **Fix side effects:** switching from substring to exact matching will start purging files that are currently (accidentally) protected — the purge may free noticeably more space after the change.
- **Discovered by:** B

---

#### F-WN-27-10  [P3] — The disk cache's "LRU" policy is FIFO-by-creation; reading a cached file does not refresh its recency
- **File:** `utils/cache_manager.py:236-237` (sort key), docstrings at `:173` and `:274`
- **Confirmed:** yes
- **Description:** `purge_stream_cache` sorts the candidates by `st_mtime` and evicts the oldest first. A file's mtime is its **write** time; reading it does not change it (only the atime moves, and Windows updates the atime lazily), so a file that is played every day is evicted before a file that was written once and never touched. The docstrings call this "LRU".
- **Cause:** mtime is used as a proxy for "last used", but nothing updates it on use.
- **Trigger conditions:** any cache above the quota with a skewed usage pattern.
- **User impact:** the tracks the user actually listens to are the ones evicted; the "least recently used" contract in the docstring is not implemented.
- **Evidence:**
  ```python
  # utils/cache_manager.py:234-237
  candidates.append((fp, file_stat.st_mtime, file_stat.st_size))
  # Sort candidates by mtime ASC (oldest first - LRU)
  candidates.sort(key=lambda x: x[1])
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wn27_probe5.py` section C — after `open(p,'rb').read(10)` the file's `st_mtime_ns` is unchanged (`1792526571583457900` before and after) while only `st_atime_ns` moves; since the purge sorts by `st_mtime`, recency is not tracked at all.
- **Suggested fix:** either touch the file (`os.utime`) when the cache serves it, or rename the policy to "oldest-first eviction"; update the docstrings accordingly.
- **Fix side effects:** `os.utime` on every cache hit adds a metadata write per playback; on Windows the atime is not reliable enough to rely on, so touching mtime is the only reliable variant.
- **Discovered by:** B

---

#### F-WN-27-11  [P3] — Every stream-cache download re-stats the entire cache tree (covers + streams + temp) while holding the size lock
- **File:** `utils/cache_manager.py:315` → `:192` → `:78-93` (recursive scan under `_size_cache_lock`)
- **Confirmed:** yes
- **Description:** `download_audio_stream` calls `self.purge_stream_cache()` on every cache miss; `purge_stream_cache` calls `get_cache_size(force_rescan=True)`, which walks the three cache directories recursively and stats every file. The walk is performed **while `_size_cache_lock` is held**, so any concurrent `get_storage_details()` (the settings screen) or `mark_cache_dirty()` blocks for the duration.
- **Cause:** the quota check and the purge are fused; the size total is re-derived from the filesystem instead of being maintained incrementally.
- **Trigger conditions:** every stream-cache download (i.e. every track played with `auto_cache_streams` enabled and no cached file present).
- **User impact:** the cost of "caching" a track is proportional to the size of the whole cache, and the settings screen can stall behind a purge. Measured cost on this machine: a full recursive stat of 3 200 files took **0.5 ms** (warm NTFS), so the effect is small today, but it is O(files) and grows with the library.
- **Evidence:**
  ```python
  # utils/cache_manager.py:315
  self.purge_stream_cache()
  ...
  # utils/cache_manager.py:192-193
  total_used = self.get_cache_size(force_rescan=True)
  ...
  # utils/cache_manager.py:81-92  (the scan runs under the lock)
  with self._size_cache_lock:
      if not force_rescan and (now - self._last_size_scan < 60.0):
          return self._cached_size_bytes
      ...
      for c_dir in cache_dirs:
          for _, file_stat in self._cache_file_stats(c_dir):
              total += file_stat.st_size
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wn27_probe5.py` section B — with 3 000 stream files + 200 cover files: `cold -> 13701822 bytes in 0.5 ms`, `cached(60s TTL) -> 0.0 ms`. The 60 s TTL is bypassed by the `force_rescan=True` on the purge path.
- **Suggested fix:** make `purge_stream_cache` use the cached size and only re-scan when it must, or maintain the total incrementally on add/delete.
- **Fix side effects:** an incremental total can drift from reality (files deleted outside the app); a periodic re-scan must remain.
- **Discovered by:** B

---

#### F-WN-27-12  [P3] — `save_cover_to_file` can write **outside** its output directory when `track_id` contains a path separator
- **File:** `utils/tag_parser.py:211-234` (filename built at `:226-227`)
- **Confirmed:** yes (the primitive); the current call graph is **not** exploitable
- **Description:** the destination is `os.path.join(output_dir, f"cover_{track_id}{ext}")` with no validation of `track_id` and no canonicalisation of the result. A `track_id` containing `..\` escapes the covers root.
- **Cause:** the module contains no filename sanitiser at all — the codebase contract explicitly states that none exists (WIN_AUDIT_CONTEXT rule #8) — and `save_cover_to_file` is a public util with an unconstrained `track_id: int` parameter that Python does not enforce.
- **Trigger conditions:** a caller that passes a non-integer id. The only current caller (`utils/file_scanner.py:143`) passes the int returned by `db.add_track`, so the defect is **latent today**; any future caller that interpolates a track title or a provider id reaches it.
- **User impact:** an image written outside `~/.nedotify/covers` (the proxy's cover root) — outside the sandbox the cover roots define.
- **Evidence:**
  ```python
  # utils/tag_parser.py:226-232
  filename = f"cover_{track_id}{ext}"
  filepath = os.path.join(output_dir, filename)
  try:
      with open(filepath, 'wb') as f:
          f.write(cover_data)
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wn27_probe.py` section E — `save_cover_to_file(b"x", "image/png", out, r"..\..\evil")` returned `<out>\cover_..\..\evil.png` and the file was created **two directories above** the covers root (`os.listdir(out)` → `['cover_42.png', 'evil.png']` — `evil.png` is in the parent).
- **Suggested fix:** coerce `track_id` to `int` (or validate it against `[0-9]+`), and/or canonicalise the destination and assert it stays under `output_dir` — the same `realpath`+`commonpath` containment the proxy uses (`core/proxy.py:170-206`).
- **Fix side effects:** none for the current caller (the id is always an int); a strict `int()` conversion would raise instead of returning `None` for a malformed id, so the error path must be handled.
- **Discovered by:** B

---

#### F-WN-27-13  [P3] — `utils/tag_parser.py` reports errors with `print()` and has no logger: parse failures are invisible in the packaged build
- **File:** `utils/tag_parser.py:89`; packaging `setup_pyinstaller.spec:104` (`console=False`)
- **Confirmed:** yes
- **Description:** the only diagnostic in the module is `print(f"[TagParser] Error parsing {filepath}: {e}")`. The packaged app is built windowed (`console=False`), so `sys.stdout` is `None` and `print` is a silent no-op (verified: `python -c "import sys; sys.stdout=None; print('x')"` raises nothing and prints nothing). The application's own log (`~/.nedotify/logs/app.log`) never receives the message.
- **Cause:** the module does not use the project's `logging` convention that every other module follows.
- **Trigger conditions:** every file that mutagen cannot parse (which, per F-WN-27-4/5, includes every WAV and every untagged file in some paths).
- **User impact:** when a file fails to import, the user gets a library entry with the filename as the title and no indication of why; support cannot diagnose it from the log.
- **Evidence:**
  ```python
  # utils/tag_parser.py:88-89
  except Exception as e:
      print(f"[TagParser] Error parsing {filepath}: {e}")
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wn27_probe.py` / `wn27_probe3.py` — the `[TagParser] Error parsing …` lines appear on the console in the source checkout and vanish entirely in a windowed build (`setup_pyinstaller.spec:104`).
- **Suggested fix:** `logger = logging.getLogger(__name__)` + `logger.warning("Error parsing %s: %s", filepath, e)`.
- **Fix side effects:** a real log line per unparseable file could be noisy during a large scan (use `debug` for the per-file case, `warning` for the summary).
- **Discovered by:** B

---

#### F-WN-27-14  [P3] — `utils/file_scanner.py`: the folder-scanning half is unreachable, the walk follows Windows junctions with no depth limit, and one bad file aborts the whole scan silently
- **File:** `utils/file_scanner.py:58-109` (walk), `:41-50`, `:157-167`, `:169-181`; `utils/tag_parser.py:217` (`os.makedirs` outside the try); watchdog caller `services/watchdog_service.py:122`
- **Confirmed:** yes for each sub-claim
- **Description:** three separate defects in one module:
  1. **Unreachable:** `scan_folder`, `scan_files`, `rescan_all_folders`, `cancel_scan` and the three callback binders have **no caller** anywhere in `core/`, `services/`, `audio/` or the UI. The bridge only exposes `open_local_file` (`core/api.py:3436-3459`), which calls `scan_single_file` once per selected file. Consequently `scan_folders` is never populated, so `services/watchdog_service.py:104-116` has nothing to watch and the "auto-import new files" feature is inert.
  2. **Unbounded walk:** `os.walk(folder_path)` has no depth limit and no skipping of hidden/system directories; on Windows `os.walk` descends into **directory junctions** (it only checks `os.path.islink()`, which is `False` for a junction), so a self-referencing junction loops forever while the `files` list grows without bound.
  3. **One bad file kills the scan:** the `_scan` body has `try/finally` but no `except`; any exception from `_import_file` (a `sqlite3.OperationalError` from `db.add_track`, an `OSError` from the unguarded `os.makedirs` in `save_cover_to_file`) propagates out of the thread, the remaining files are never imported and `on_complete` is never called. In the packaged build the traceback goes to a `None` stdout and is lost.
- **Cause:** the module was written for a folder-import feature that the bridge never wired up; the walk was never hardened and the scan body has no error boundary.
- **Trigger conditions:** (2) a music folder containing a junction (OneDrive/backup tools create them); (3) a single unreadable file in a folder.
- **User impact:** an infinite scan (no progress, growing memory) or a scan that silently stops halfway with no way for the user to learn why.
- **Evidence:**
  ```python
  # utils/file_scanner.py:70-80  (no depth limit, no skip list, whole list materialised)
  if recursive:
      for root, dirs, filenames in os.walk(folder_path):
          for fname in filenames:
              fpath = os.path.join(root, fname)
              if is_audio_file(fpath):
                  files.append(fpath)
  ...
  # utils/file_scanner.py:65-106  (try/finally, no except)
  def _scan():
      try:
          ...
          track = self._import_file(filepath)
      finally:
          with self._scanning_lock:
              self._scanning = False
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wn27_probe3.py` — section 1: a `mklink /J` junction inside the scanned tree was visited by `os.walk` (`os.path.islink(link): False`, `os.path.isjunction: True`), i.e. the walk follows it; section 3: a `FileScanner` whose `db.add_track` raises for one file produced `scan thread alive after join: False`, `on_complete called: False` and the traceback `utils/file_scanner.py:89 → _import_file → add_track → Boom`.
- **Suggested fix:** either wire the folder import into the bridge (making the walk live and worth hardening) or delete the dead half; add a depth limit / junction check (`os.path.isjunction`, Python ≥3.12) and a per-file `try/except` around `_import_file`.
- **Fix side effects:** adding the folder import changes the library-import UX and the DB write volume (one row per file) — that is a product decision, not a bug fix.
- **Discovered by:** B (the watchdog's use of the private `_import_file` is WN-25's misuse)

---

### 3. Clean areas

- **`utils/url_safety.py` itself is sound.** Empirically it rejects every dangerous form I could construct: `127.0.0.1`, `localhost`, decimal (`2130706433`), hex (`0x7f000001`) and octal (`017700000001`) IPv4 literals, `[::1]`, `[::ffff:127.0.0.1]`, `[fe80::1]`, `0.0.0.0`, `169.254.169.254`, `10/8`, `192.168/16`, `224/240` (multicast/reserved), `file://`, `javascript:`, `data:`, UNC `\\server\share`, credentials-in-URL (`http://user:pass@127.0.0.1`), and every DNS failure (fail-closed). It requires **all** resolved addresses to be public. `tests/test_media_guard_f3.py:31-92` pins exactly these cases. The defect is that the module is bypassed (F-WN-27-7), not that it is wrong.
- **`utils/search_query.py` is bounded and fast.** The Levenshtein DP (`_distance`, `:13-28`) keeps only two rows (`previous`/`current`) → O(len(right)) memory, with two early exits (`abs(len(left)-len(right)) > ceiling`, `min(current) > ceiling`). Measured: 5 000 × 5 000 → 18.5 ms (early exit), 240 × 240 → 0.6 ms. The candidate set is hard-capped at 4 000 and each candidate at 240 chars (`:71`, `:79-84`); the query is capped at 3–120 chars (`:32`). End-to-end `suggest_search_queries` over a 600-row library measured **2.7–4.2 ms** — no performance finding. Input validation is strict (non-str, wrong `limit` type, empty words → `[]`).
- **`utils/stream_urls.py` is correct and cheap.** `stream_url_expired` only interprets the explicit `expire`/`Expires` tokens (with a 60 s margin), ignores unknown/malformed parameters by design, and swallows `TypeError/ValueError/OverflowError`. No network, no I/O. It is used consistently by `core/resolver.py:16`, `core/api.py:22`, `core/playback_recovery.py:10`, `services/base_service.py:15`.
- **`utils/cache_manager.py::save_cover_from_url` (`:398-453`) is the best-written download path in the codebase**: scheme allow-list (`http`/`https` only), the SSRF guard, a `_SafeRedirectHandler` that re-checks **every** redirect hop, download to a `.part` file, a zero-byte check, and a final `os.replace` (atomic). `CacheManager.save_cover_from_url` is the only cover writer in the app that is atomic — but it has **no callers** (see ARCH-6).
- **`CacheManager`'s locking discipline for its own state is correct**: `_active_downloads` is guarded by `_active_downloads_lock` on every mutation (`:295-298`, `:389-390`, `:395-396`), `_size_cache_lock` guards the size cache, and `_cache_file_stats` skips symlinked directories (`:69-70`), so it cannot be trapped in a symlink loop. The `.part` file of an in-flight download is protected from the purge by the `_active_downloads` substring check (`:231-232`).
- **The proxy's file-serving side is properly hardened** (`core/proxy.py:141-206`): `realpath` + `commonpath` containment, an extension allow-list, and roots that do not exist are dropped. The cover roots cover all three naming conventions the app writes, so the traversal issue in F-WN-27-12 cannot be escalated into an arbitrary read through the proxy.
- **`utils/tag_parser.py::_extract_cover` does not read the whole file into memory** — it returns only the first picture's bytes (`apic.data`, `pic.data`), and for OGG it base64-decodes a single `metadata_block_picture`. It never loads the audio frames. (The *caller* in `core/api.py:3939` is the one that reads a whole file into RAM — F-WN-27-6.)
- **File handles are closed on all paths** in the reviewed modules: every `open()` in `utils/cache_manager.py` (`_clear_dir` uses `os.remove`/`shutil.rmtree`, `save_cover_from_url` uses `with`), `utils/file_scanner.py` and `utils/tag_parser.py` is inside a `with` block or a `try/finally`; `os.scandir` is used as a context manager in `_cache_file_stats` (`utils/cache_manager.py:65`) — **except** in `core/api.py:3609` (`os.scandir(streams_dir)` without `with`), which belongs to WN-10.
- **`utils/file_scanner.py:16` correctly derives `AUDIO_EXTENSIONS` from `tag_parser.SUPPORTED_FORMATS`** instead of duplicating the list — the single "is this playable audio" predicate for the live code path.

---

### 4. Coverage gaps

- **No FLAC/M4A/OGG/WMA fixtures exist in the repository** (only fake MP3s, a `test-tone*.wav` set and one real-but-invalid MP3 under `.test_runs/`). The FLAC atomicity claim in F-WN-27-1 therefore rests on the mutagen source (`mutagen/flac.py:861-882`: `resize_bytes(...)` → `f.write(b"fLaC")` → `f.write(data)`), not on an executed FLAC round-trip. Building a valid FLAC header by hand was attempted and rejected by mutagen ("file said 16252928 bytes, read 62 bytes").
- **The cache-manager cost measurements use a synthetic tree** (3 200 files, 13 MB, warm NTFS, 0.5 ms per full scan). I did not measure against a real 5 GB / 50 000-file cache on a slow or spinning disk, so F-WN-27-11's practical severity is uncertain.
- **The DoH fallback path was not exercised end to end** (no network in this environment), so the "up to ~6 s per `is_safe_media_url` call" figure in F-WN-27-8 is derived from `main.py:200-221` (`timeout=2.0` × 3 endpoints) plus the OS resolver timeout, not measured.
- **DNS rebinding (F-WN-27-8) is a hypothesis, not a demonstrated bypass**: the TOCTOU window is real by construction (the guard resolves, the HTTP client resolves again), but I did not build a rebinding resolver to prove an internal address is reachable through the proxy.
- **The UI's reaction to a scan that ends without `on_complete` was not verified** — the three `FileScanner` callbacks have no subscribers, so there is currently nothing to hang; a future wiring must handle it.
- **`services/watchdog_service.py:122` calling the private `scanner._import_file` was noted but not judged** — that is WN-25's misuse of my area's API (ARCH-7).
- **The JS side of the cover-file naming conventions** (which file the UI actually requests) was not read — that is WN-28/WN-32.
- **`core/api.py::_clean_stream_cache` was exercised through an unbound call with a stub `self`**, not through a live bridge; the file-deletion and dangling-DB-row results are therefore confirmed at the unit level, not at the UI level.

---

### 5. Architecture improvements (ARCH)

**ARCH-1 — `utils/` is not a layer; it depends on `core/`, and the two packages import each other.**
`utils/cache_manager.py:13` → `from core.database import DatabaseManager`; `utils/file_scanner.py:11` → `from core.database import DatabaseManager`; `utils/cache_manager.py:407` → `from core.proxy import _is_ssrf_safe_url` → `core/proxy.py:23` → `from core.api import _is_ssrf_safe_url` → `core/api.py:3966` → `from utils.tag_parser import write_tags`. A package-level cycle `utils ↔ core` exists and is broken only by deferred (function-local) imports. *Direction:* invert the dependency — `utils/` should depend on nothing but the stdlib; the schema knowledge and the SSRF policy it needs should be injected (a `DatabaseManager` protocol, a `url_safety` call) or moved into `core/`.

**ARCH-2 — One cache, three owners.** See F-WN-27-3. `CacheManager` should be the only component allowed to delete anything under `~/.nedotify/streams`; `AppApi._clean_stream_cache` and `db.cleanup_expired_cache` should become thin calls into it. A single "cache policy" object would also let the settings quota and the API's hard-coded 350 MB stop disagreeing.

**ARCH-3 — Two SSRF policies.** See F-WN-27-7. `utils/url_safety.py` should be the single implementation, with the memoisation currently living in `core/api.py` moved into it, and `core/api.py::_is_ssrf_safe_url` reduced to a delegating wrapper (or deleted).

**ARCH-4 — Two "is this audio?" predicates.** `utils/tag_parser.py:26` (`SUPPORTED_FORMATS`, used by `utils/file_scanner.py:16` to build `AUDIO_EXTENSIONS`) and `utils/tag_parser.py:26`'s own `is_audio_file` (which uses the same set but is **dead** — nothing imports it) coexist in the same package. *Direction:* one predicate, one place.

**ARCH-5 — Three naming conventions in one directory.** `~/.nedotify/covers` receives `cover_<id>.<ext>` (`utils/tag_parser.py:226`), `cover_<id><ext>` (`utils/cache_manager.py:430`) and `<id><ext>` (`core/api.py:3954`), and the proxy serves all of them (`core/proxy.py:141-167`). One writer should own the directory and the naming (a `CoverStore` next to `CacheManager`), so a cover is written once, atomically, and is invalidated when the track's cover changes.

**ARCH-6 — The good code is the dead code.** `CacheManager.save_cover_from_url` (atomic, SSRF-guarded, redirect-re-checking) and `CacheManager.enforce_cache_limit` (a thin, correct quota delegate) have **no callers**; meanwhile `core/api.py` writes covers non-atomically with an unbounded read (F-WN-27-6). *Direction:* route the cover write through the atomic implementation.

**ARCH-7 — `utils/file_scanner.py` is a half-dead module and its API is private-by-convention.** The folder-import half has no bridge entry point (F-WN-27-14) and `services/watchdog_service.py:122` reaches into the private `scanner._import_file`. *Direction:* either expose a proper `import_paths()` API on the bridge or delete the unused half; expose an `import_file()` public method for the watchdog.

**ARCH-8 — `utils/cache_manager.py` writes `core.database`'s schema directly and bypasses its write lock.** `purge_stream_cache` executes `UPDATE stream_cache ...` / `UPDATE tracks ...` (`utils/cache_manager.py:255-265`) against tables it does not own, and without `DatabaseManager._write_lock` (`core/database.py:156`), violating the "a new shared field joins its class's existing lock" rule. *Direction:* move the purge's DB bookkeeping into `DatabaseManager` (e.g. `db.clear_cached_files(paths)`), so the schema and the lock stay in one place.

**ARCH-9 — `utils/tag_parser.py` mixes three responsibilities**: file-type detection (`SUPPORTED_FORMATS`), reading (`parse_tags`, `extract_embedded_lyrics`), and writing (`write_tags`, `save_cover_to_file`). The read path and the write path have different format coverage (F-WN-27-5) and different safety properties (F-WN-27-1) and evolve independently — a reader/writer split with an explicit per-format capability table would make both honest.
