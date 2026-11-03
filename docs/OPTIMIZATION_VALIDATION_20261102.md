# Windows optimization and functional verification

Only the Windows checkout was changed. The current and macOS presentation
packs share the playback/search logic; controls were verified in both packs.
No product animation, blur, transparency, effect intensity, or FPS preference
was reduced for performance.

## Measured work

- Repeated unchanged cover sampling: five repetitions of 1000 calls. Median
  46.4 ms before and 0.3 ms after; 5000 temporary canvas contexts replaced by
  one 50×50 sampler. Identical RGB output is required. Successful samples use
  weak image keys; source/dimension changes invalidate them, failed reads remain
  retryable. This is a controlled work-unit measurement, not a claim that the
  whole app uses 99% less CPU or GPU.
- Real FFmpeg conversion with 300 ms synthetic artwork IO: median 511.99 ms
  serial versus 303.662 ms overlapped, five runs each. Actual MP3 output is
  320 kbps with the same encoded audio hash, tags and embedded cover.
- SoundCloud fallback reuses the existing YouTube provider and its pools/cache
  instead of constructing new providers for repeated requests.
- Invalid proxy configuration is diagnosed once per bounded cached value,
  replacing a warning on every provider request. The regression changes 1000
  warnings into one, without installing an invalid proxy.
- Native WebView process-tree diagnostic completed via native CDP. One short
  500-track idle control measured about 10.14% of one CPU core and 721.69 MiB
  summed process RSS. This is a single current measurement, not a before/after
  reduction; summed RSS includes shared browser pages. GPU engine utilization
  was not measured. The settings native runs retain normal rendering.

Artifacts: `tools/bench/results/cover-sampler-{before,after}-20261101.json`,
`download-processing-20261101.json`. The native process report is stored under
the temporary NeDotify benchmark results directory as
`resource-native-20261101-20261101-222041.json`.

## Search, controls and progress

See `search-live-verification-2026-11-01.md` for real lyric and artist discovery,
including unsuccessful network attempts. Public real matches include Adele —
Hello and a Russian lyric match for Группа крови. Artist discovery, selection
and a complete profile with tracks were verified through iTunes and Deezer.
Ordinary title/artist searches do not unconditionally invoke lyric discovery.

All 48 range controls were checked in current and macOS layouts through the
real WebView2 → AppApi → SettingsManager → SQLite path: displayed value,
saved value, acknowledgement, reload and restoration. EQ persistence now waits
for the durable batch; rejected writes roll back. Native artifacts are under
`tools/bench/results/settings-native-20261101-223043/`.

The bottom line is replaced by the Riff-style wave without an additional RAF
loop. Elapsed/duration labels occupy a separate row. Both UI packs, narrow
windows, zoom, pointer/keyboard seeking and paused appearance changes were
checked. Riff MIT attribution is retained.

## Downloads and TUN routing

`live-downloads-followup-20261102.json` records actual full validated downloads
through the shipped service and DownloadContext: SoundCloud 5.66 s / 1,865,436
bytes, YouTube 4.38 s / 3,433,755 bytes, Deezer 5.86 s / 4,039,652 bytes,
Spotify 6.13 s / 3,433,755 bytes. These are individual observations, not a CDN
bandwidth improvement percentage. Earlier network failures remain documented.
Yandex live download remains unverified because the stored value does not have
a valid OAuth token shape. User settings and credentials were not changed.

Read-only Find-NetRoute checks confirm provider IPv4/IPv6 routes select
`happ-tun`; neither Happ nor Windows routing was changed. The explicit malformed
application proxy is ignored. The current DNS answers are public and do not
trigger the DoH fallback. Forcing the existing wildcard IPv4 source address
was not demonstrated to bypass TUN.

## Follow-up: home and SoundCloud playlist playback

The user's current log confirmed the card did invoke Play; the failure occurred
in stream preparation. Reversed the overly aggressive early exit after a
native SoundCloud API timeout: the same-source SDK transport is again tried
before a cross-provider fallback. A regression requires API timeout + working
SDK to produce the requested SoundCloud stream, with no permanent failure memo.

An additional reproduced bug: extensionless HLS manifests on
`*.soundcloud.cloud/.../playlist/...` were assigned to native audio instead of
HLS.js. The loader now recognizes that provider-specific manifest shape, while
ordinary `sndcdn.com/playlist/track` remains a direct audio URL. Existing HLS,
seek, resource and recovery tests pass. Native playback verification is being
captured by `tools/bench/check_soundcloud_native.py` without API stubs.

Native verification also reproduced a separate same-track replay bug: when
the cached URL did not change, an explicit autoplay request left the active
element paused. The duplicate-stream guard now permits restarting a paused
element on an explicit autoplay request; paused session restoration is retained.
The regression failed before the fix and passes afterward.

The final native run at
`tools/bench/results/soundcloud-native-20261102-082430/result.json` passed for
both current and macOS. It calls real `AppApi.play_track`, requires the media
clock to pass 1.2 seconds with buffering false, then verifies it keeps advancing.
It pauses and explicitly replays the cached same track when switching UI packs.
Both reach approximately 2.6 seconds of decoded playback. Physical speaker
output was not assessed. Earlier unsuccessful native runs are retained, including
one diagnostic script error (`api.pause` corrected to the real `api.play_pause`).
The user's existing process was then closed via its normal shutdown route and
NeDotify restarted to load these changes.

The complete suite after the playback follow-ups passed 2650 tests,
with 9 skipped and 1 deselected in 114.39 seconds. Follow-up selections also
passed 151 and 89 tests. Native decoded playback passed in both Windows packs.

## Follow-up: measured five-second playback target

See [playback-startup-20261102](perf/playback-startup-20261102.md) for the
reproduced stale SoundCloud signature, repeated TLS handshakes, visitor-header
initialization and CDN handshake stalls, plus retained unsuccessful runs. The
latest 32 real native launches across both Windows layouts all reached advancing
unbuffered media within five seconds: maximum 4.464 s, median 1.275 s, 24 of 32
within three seconds. These include SoundCloud tracks from the user log and
YouTube/Spotify/Deezer, both layout orders, separate cold starts and copies of
three relevant user URL-cache rows. The user also confirmed actual home and
SoundCloud playlist playback within five seconds. Audio selection and UI
visual effects were not reduced. This does not establish whole-app resource
reductions or live playback for providers lacking valid account credentials.
