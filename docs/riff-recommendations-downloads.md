# Riff reference: recommendations and downloads

Inspected source: [rootscripts/riff, commit fa33ad0ab566979a557e2418c45437e2b336a371](https://github.com/rootscripts/riff/tree/fa33ad0ab566979a557e2418c45437e2b336a371), version 43.2.2, inspected 2026-10-29. License: MIT, copyright (c) 2026 rootscripts; notice retained in `licenses/riff-MIT.txt`. Adaptations below are independent Python implementations of the architecture, with no Electron/Node source copied into the application.

## Source inspected

- `src/server/server.js`: `gatherCandidates`, `rankCandidates`, `pickWeightedSeeds`, `recommendVibeTracks` (around lines 1122–1450): concurrent metadata candidates, stronger favorite seeds, canonical song deduplication, artist diversity, avoid lists, expiring caches, bounded resolution workers.
- `src/renderer/app.js`: `handleDailyMixRating` (around 8640), `recordWaveSkip` (21605), `extendMyWaveQueue`/`ensureInfiniteWaveQueue` (22215 onward), `generateDailyMixes` (23409): persisted feedback, measured skips, queue avoidance and low-water refill, day cache for mixes.
- `src/server/server.js`: `downloadTrackToDisk` (1754), `findDownloadedFile` (3647), `handleDownload` (around 3700–4060): in-flight promise deduplication keyed by recording/output policy, completed cache before network fetch, cached audio converted with ffmpeg, output metadata and cover, child-process cancellation and cleanup, bounded retries/source fallback.
- `package.json`, `package-lock.json`, and binary resolution in `src/server/server.js`/`src/main/main.js`: Electron 41, hls.js 1.7, Tone 15; yt-dlp and ffmpeg run as external tools. None of these JavaScript dependencies is added to NeDotify. Its existing verified Setup tools, yt-dlp providers, Mutagen writers and ffmpeg remain in use.

## Applied to NeDotify

The existing feed/radio already had bounded concurrent candidates, local taste signals and per-track/artist avoidance. The remaining older smart-home implementation bypassed those paths. It now shares `_profile` and `_feed_tracks` with Mix/Wave, honors supplied history and current source choices, preserves local track ids/file paths, and applies dislikes immediately rather than serving a stale home-only cache. Home sections describe actual familiar/discovery results instead of presenting fallback songs as new releases or charts. Independent seed-artist evidence contributes a bounded ranking bonus, following Riff's multi-seed corroboration without counting duplicates from the same artist. Provider failure retains usable local favorites; errors remain visible when there is no usable fallback.

Source opt-outs now affect candidate requests, cached feeds, metadata resolution, playback recovery, SoundCloud-to-YouTube fallback, Deezer audio mapping and queued provider transfers while downloaded/local files remain playable. Riff's probabilistic seed selection and random ranking jitter were not copied: NeDotify keeps deterministic ranking and its existing measured listening weights.

The downloader already had durable jobs, native format policies, retries, cancellation, shared tool leases and track deduplication. Its cache reuse was restricted to original format. It now reuses verified complete audio for requested output conversions as Riff does, skips the yt-dlp requirement for cache-only jobs, and copies the immutable cache cooperatively with cancellation checks and partial-copy cleanup. Lossy cached files are not reused for a FLAC request. Existing queue limits, chosen quality, tags, atomic publication and original library/cache files are preserved.

Riff's disabled TLS certificate checks, DRM-error fallback classification, broad artifact deletion and title-only output names were deliberately not imported. NeDotify retains verified TLS, permanent DRM errors, task-owned cleanup and identity-suffixed safe filenames.

## Verification

`tests/test_riff_adaptations.py` reproduces history loss, local-file re-resolution, stale feedback/source cache and repeated network fetch before conversion. The conversion test uses actual ffmpeg and verifies original cache bytes remain unchanged. The broader recommendation, taste, queue, cancellation, transport, retry and resume suites are also run. These isolated tests do not establish live provider availability or audible playback, and no unmeasured overall speedup is claimed.

A separate live check ran `tools/bench/check_live_download.py --provider youtube --target jNQXAC9IVRw` against the public 19-second upload “Me at the zoo” in a disposable profile: success, 252182 bytes, 17.1 seconds, audio-container validation passed. The older yt-dlp test fixture `BaW_jenozKc` returned “This video is unavailable” after 4.01 seconds; it was reported as an error. The successful live check verifies one anonymous provider transfer, not UI decoding, audible playback or every provider. No user library, credentials or browser cookies were used by the disposable check.

