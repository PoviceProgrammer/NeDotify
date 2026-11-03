# Deezer, downloads and playlist imports — 2026-10-23

Windows desktop changes in `ui/web_new_v2/` and the Python backend.

## Deezer

Deezer supplies track, album and public-playlist metadata. Search includes a
dedicated Deezer selector and Deezer in the combined results. Album and playlist
views preserve Deezer identities, covers and ordering.

Full audio is selected from the existing YouTube and SoundCloud providers.
Candidates must match artist, title, version and duration through
`same_recording`. Deezer's 30-second previews are never used as full tracks.
Downloads try a verified SoundCloud candidate if the YouTube transfer fails;
pause/cancel interrupts this fallback. The stored library identity stays Deezer.

Public playlist imports read all pages up to the existing 2,000-track limit.
Pagination URLs from the API are not followed: requests stay on the fixed Deezer
API host. Incomplete pages and oversized playlists fail before database writes.
Repeated imports reuse tracks and memberships through `import_playlist_atomic`.

## Download recovery

- Truncated transfers and failed container checks enter the queue retry policy.
  Invalid completed files are removed only inside the managed downloads folder.
- Missing HLS/DASH fragments fail the attempt instead of being silently skipped.
  Existing resume filenames, partial files, pause and cancellation remain active.
- Transport/body errors are retryable. Numeric `Retry-After` is respected up to
  300 seconds while releasing the download worker for other queued tracks.
- SoundCloud metadata timeouts reach the retry policy. A fallback recording is
  checked before its audio is downloaded.
- Mutagen does not parse WebM. WebM files are checked with an available ffprobe,
  including audio packet presence and parser errors. Without ffprobe, YouTube
  prefers M4A and other containers supported by Mutagen. No new binary is required
  for the normal M4A download path.

## Import fixes

M3U relative file paths resolve against their playlist directory. Text track
lists generate `ytsearch1:` expressions instead of treating titles as video IDs.
UTF-8 BOM files are accepted. Provider URL detection checks exact hostnames.
The import UI lists YouTube, SoundCloud and Deezer; the importer also handles
M3U/M3U8, JSON and text files. Spotify and Yandex playlist URLs were not supported
by this importer before this change and remain unsupported.

## Verification

The offline regression suites cover provider routing, queue recovery, corrupt
audio, partial transfers, cancellation, import rollback and deduplication,
bridge events and frontend JavaScript. A separate network test exercises the
live Deezer search and complete public-playlist metadata import.

Final full-suite result: **1,772 passed, 1 skipped, 1 network test deselected**.
The skip is `test_build_and_brand.py` checking an absent `CLAUDE.md`. The live
Deezer network test was also explicitly run and passed separately.

Live downloads were run with anonymous access in disposable profiles using
`tools/bench/check_live_download.py`. The real user library was not accessed.
Observed successful samples:

| Route | Bytes | Elapsed, including lookup/extraction |
|---|---:|---:|
| YouTube, `dQw4w9WgXcQ` | 3,433,755 | 29.44 s |
| SoundCloud, `the80m/the-following` | 8,013,083 | 21.60 s |
| Deezer, `14408104`, matched to YouTube | 3,433,755 | 45.45 s |

These are single connectivity checks, not before/after performance benchmarks.
The SoundCloud sample `odesza/bloom` was DRM-protected and its fallback metadata
could not be obtained. Deezer `66609426` had no sufficiently exact audio match
among the returned candidates. Those samples failed rather than saving a preview
or a different recording. Provider restrictions and network availability remain
external constraints. Native UI/audio playback and a rebuilt installer were not
verified by these download checks.
