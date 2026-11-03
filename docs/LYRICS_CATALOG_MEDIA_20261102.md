# Windows: lyrics coverage, artist catalogues and media controls

Implemented in the shared Windows frontend and backend; verified with the
`current` and `macos` Windows layouts. Android and Linux were not edited.

## Lyrics

Three additional public lookup routes now participate in the existing bounded
cascade: lyrics.ovh plain lyrics, Better Lyrics QQ, and Kugou lyric search/LRC
download. These services overlap in underlying catalogues. They are additional
working routes, rather than a count of independent music databases.

All adapters retain the shared eight-worker executor, eight-second lookup
budget, response size limits, per-provider request ceilings, rate-limit cooldowns
and identity checks. Completed or superseded lookups now stop a running source
before it starts another request. Direct requests reuse the existing verified,
DNS-pinned public TLS transport; configured application proxies retain their
existing path, and system proxy/TUN routing remains in use. No model, audio
inference, new runtime dependency or synthetic timing was added.

Remix/sped/slowed lookups retain the existing original-text fallback, with
original karaoke timestamps removed when they do not describe the played edit.
QQ responses with literal line breaks inside XML attributes now parse using
their numeric line headers. Embedded QRC title/artist fields are required;
missing duration yields plain text. Genius bilingual Russian/Latin titles are
normalized for matching while unrelated artist/translation accounts remain
subject to the artist check.

For an identified SoundCloud/YouTube reupload without explicit title credits,
recovery requires exact title/version, a tight duration window, and agreement
between Deezer and NetEase on one artist identity. Conflicting identities or
missing duration reject recovery. Recovered lyrics are plain; the user's
library artist/uploader fields are preserved.

The supplied example is the public SoundCloud track `303974832`, 219.057 seconds,
“Сукины дети” / Danzal_Parkour. Live Deezer and NetEase metadata agreed on
1.Kla$ (220 and 220.517 seconds). NetEase's first matching release had empty
lyrics; Genius supplied the text after the independently confirmed identity
was used. Native playback and the ordinary `lyrics_ready` bridge delivered
45 visible lyric lines in both Windows layouts.

Live adapter/lookup result:
`tools/bench/results/lyrics-coverage-20261102-145422.json`:

| Operation | Wall time | Process CPU time |
| --- | ---: | ---: |
| lyrics.ovh public test | 402 ms | 47 ms |
| Better Lyrics QQ public test | 392 ms | 0 ms at timer resolution |
| Kugou public test | 958 ms | 0 ms at timer resolution |
| User reupload, cold lyric cache | 3343 ms | 234 ms |
| Same lookup, memory cache | 0 ms rounded | 0 ms at timer resolution |

These are backend operation measurements; whole-application CPU/GPU/RAM
reduction is not established by them. Retained earlier attempts record an
unavailable LRCLIB response and a transient lyrics.ovh transport timeout.
Provider availability and catalogue coverage are not universal.

The final playback regression check exposed one 17-second SoundCloud startup
(`playback-latency-20261102-150713`). Automatic remote lyric requests now wait
for advancing decoded audio. Cached/local lyrics and paused restores remain
immediate, and a manual lookup remains available. Changing tracks invalidates
the previous backend lookup using the existing playback epoch. The regression
tests exercise these actual scheduling and cancellation paths.

A real loopback TLS test also reproduced a reused connection accepting a new
GET/HEAD but never returning response headers. Only that reused connection's
header wait is shortened before the existing single fresh verified retry.
Fresh connections and response-body reads retain the caller's full timeout,
including `Connection: close` responses. GET/HEAD recovery, slow healthy fresh
headers, and slow reused/fresh bodies pass five real TLS tests. This proves the
transport failure mode; the earlier native trace alone does not establish it
as the cause of every observed network delay.

After both changes, `playback-latency-20261102-152306` passed all 14 real-audio
launches in both Windows layouts with three user URL-cache rows copied read-only
to a disposable profile. Maximum time to advancing audio was 4.090 seconds.
The reversed-order repeat `playback-latency-20261102-152414` also passed 14/14
(maximum 3.928 seconds). Together these are 28/28 advancing-audio starts within
five seconds. Fresh native lyric checks after scheduling/cancellation changes
also passed in both layouts (`lyrics-native-20261102-152449` and `152502`),
with real audio advancing and 45 lyric lines visible.

Native evidence, separate fresh profiles and real audio:

- `tools/bench/results/lyrics-native-20261102-145956/result.json` — current.
- `tools/bench/results/lyrics-native-20261102-150007/result.json` — macos.

Public API/source references:
[lyrics.ovh](https://github.com/NTag/lyrics.ovh#api),
[Better Lyrics provider endpoints](https://docs.betterlyrics.org/reference/get-lyrics#provider-specific-endpoints),
[Kugou request contract used by LyricsKit](https://github.com/ddddxxx/LyricsKit/blob/master/Sources/LyricsService/Provider/Kugou.swift).
The adapters are independent Python implementations; no LyricsKit Swift code
was copied.

## Artist identity and complete available catalogue

Chooser cards now carry real, provider-ID-filtered track previews. One batched
iTunes lookup enriches multiple candidates. A hint track is checked against all
competing candidates before a unique selection is allowed. Genuine homonyms
remain selectable; confirmed hint matches sort first and display their evidence.
The six iTunes PHARAOH entries have distinct real artist IDs and different
catalogues (including Metal and Chinese Hip-Hop); merging them by name would
misattribute recordings.

Initial and incoming track pages deduplicate by provider recording ID. Confirmed
remixes remain available. Album/single discovery resumes from saved cursors
after deadlines or failures; a large album shelf no longer suppresses singles.
Deezer album and track pages continue through the existing page bridge, including
albums with more than 100 tracks. The interface reports partial catalogues and
iTunes's release limit, and its load-more control continues the real catalogue.
The initial five rows remain the compact popular-tracks preview.

Live PHARAOH, Deezer artist `10216612`: 14 pages, 41 albums, 167 unique credited
recording IDs, ending with `has_more=false`. A separate traversal of all album
tracklists produced exactly the same IDs: zero missing, unexpected or duplicate
IDs. Evidence: `tools/bench/results/artist-deezer-full-live-20261102.json`.
Real iTunes/Deezer hint evidence is retained in
`tools/bench/results/artist-identity-hint-live-20261102.json`. Initial YouTube
Music searches returned no artists/songs, and an earlier iTunes request timed
out; these unsuccessful probes remain in the results directory.

## Search and headphones

Quick genre chips and their unused styles were removed. Recent searches now
use themed button rows, individual deletion, clear-all and an empty state.
Arrow keys, Escape, keyboard activation and repeat search work in both layouts.
The surrounding search capsule supplies the keyboard focus indicator.

MediaSession play/pause now controls the frontend audio owner with idempotent
intent checks. Its old backend call only reported state and could not toggle
audio. Windows media-session routing supplies headphone/media-key support
while unfocused or minimized, with no competing native window hook or polling.
The gesture remains configured by the headphones/Windows; physical headset
hardware was not tested.

Corrected native harnesses identify the window strictly by the benchmark PID:

- `tools/bench/results/media-search-20261102-150054/result.json` — current.
- `tools/bench/results/media-search-20261102-150119/result.json` — macos.

Eight play/pause transitions and four next/previous commands passed across
foreground/minimized states and both layouts. Dropdown deletion, clear-all,
empty state, arrow navigation, Escape and repeat search also passed. Commands
were spaced two seconds apart; an earlier 800-ms sequence was intermittent.
Earlier runs that selected a window by title were superseded by PID-bound runs.

## Regression validation

New regressions first reproduced missing reupload lyrics, bilingual title
rejection, QQ XML line loss, work continuing after lookup completion, artist
identity mistakes, discarded remixes and interrupted catalogue discovery.
Existing remix-exclusion assertions were updated to the user's current request
while retaining foreign-artist rejection and cursor/failure checks.

The final full default suite passed **2716 tests**, with 9 skipped and one live
network test deselected, in 108.99 seconds, including the final scheduling,
cancellation and TLS recovery changes. All 269 lyrics-related tests passed
in a separate run. Artist suites and browser checks covered both layouts.
Source inventory, dependency consistency and scoped whitespace checks passed.

The first full run exposed three older assertions that deliberately excluded
confirmed remixes; those expectations were updated for the current request.
It also encountered a transient Windows connection abort in the unchanged
foreign-origin rejection server test. That server suite then passed 10/10,
and the complete final suite passed without a server code change.

At 15:27 Moscow time the updated app was launched with the existing user
profile. Native PID 20668 was visible, not minimized and responding;
the frontend acknowledged bridge readiness. User library/settings were retained.
