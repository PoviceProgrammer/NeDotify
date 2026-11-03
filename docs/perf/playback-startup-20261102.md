# Windows playback latency, 2 November 2026

The user's 08:52 log showed SoundCloud 403 cache failures, a transient public
DNS validation failure for Googlevideo, and a separate DRM-only recording.
The earlier isolated playback success did not establish that this was fixed.
The user subsequently set a hard measured target of at most five seconds from
Play to playback, with three seconds preferred.

## Reproduced faults and changes

1. SoundCloud's CloudFront URL contains a lower-case `expires` value hours away
   and a **shorter signed Policy deadline**, only minutes away. Both provider
   and database caches ignored the latter, returning dead URLs for a later
   click. `stream_url_expired` now checks both deadlines locally, without an
   extra request. Malformed policies remain bounded and non-fatal. Reference:
   [CloudFront custom policies](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/private-content-creating-signed-url-custom-policy.html).
2. Each HLS manifest/segment performed another TCP/TLS handshake. The guarded
   urllib transport now shares a bounded pool of fully consumed idle direct
   connections between proxy request threads. In-flight sockets have one owner;
   partial/error responses cannot return to the pool. System proxies still use
   urllib's normal handlers. Redirect checks, DNS pinning and certificate/SNI
   verification remain in force. Riff's keepAliveHttpsAgent at
   `fix/riff-v44.0.0/src/server/server.js:3` is the architectural reference;
   no Node transport code was copied.
3. A CDN address could accept TCP and stall TLS for 12 seconds. The transport
   now staggers up to two vetted addresses, through both TCP and TLS, using a
   selector and one total deadline. It closes losing sockets and does not
   create extra connection worker threads. An actual loopback TLS regression
   reproduces the stalled first address and working second address; another
   verifies a mismatched certificate is rejected.
4. SoundCloud's existing public-client preparation now starts while the window
   loads. The official asset's client ID is validated by the requested catalog
   operation and the existing 401/403 refresh path, rather than a throwaway
   search. Short verified static VOD manifests can be reused for ten seconds,
   at most eight bodies of 64 KiB; live manifests, keys and segments are not
   cached by this memo. Riff uses its scraped client ID without a test search
   (`server.js:798`).
5. First Spotify playback additionally initializes ytmusicapi's public visitor
   headers before the real YouTube Music search. This initialization now starts
   during window loading and shares one in-flight operation with searches.
   No track is downloaded to warm the service. The SDK's cached_property is
   otherwise not single-flight on Python 3.14.
6. The same verified TLS establishment now covers direct requests sessions in
   SoundCloud and YouTube Music, plus each YouTube SDK requests pool. The SDK's
   own sessions, cookies, redirects, SSL policy and proxy managers remain in use;
   there is no global monkeypatch. One-address CDN names can use one delayed
   fresh TCP/TLS attempt if their first handshake stalls. Real loopback tests
   cover direct requests, SDK requests, certificate rejection and an explicit
   HTTP CONNECT proxy. urllib3 is declared as a direct runtime dependency.

These backend paths are shared by current and macOS Windows layouts. Neither
UI appearance nor the selected audio quality was reduced. The user's library,
credentials, Happ configuration and Windows routes were not changed. Read-only
Find-NetRoute on this run selected `happ-xray` for both CDN address samples.

## Native measurement

`tools/bench/check_playback_latency_native.py` creates a disposable profile and
uses the actual AppApi, providers, loopback proxy, HLS.js and Windows WebView2.
It measures from `api.play_track` to an advancing decoded media clock with
buffering false, then requires continued advancement. It does not use API
stubs or fabricated media. It does not measure physical speaker output.

The four SoundCloud IDs are the non-DRM tracks in the user's log:
2215597907, 2104544877, 2331544133 and 2289890927. Additional public test
recordings cover YouTube, Spotify's verified catalog mapping and Deezer.
The second layout in each process reuses provider caches; reverse-order runs
ensure both layouts also receive the first cold playback.

Selected **retained** artifacts under `tools/bench/results/`:

| Artifact directory | Result |
| --- | --- |
| playback-latency-20261102-090029 | Reproduced SC 5.97–16.78 s cold, 2.44–2.55 s warm; YouTube 4.09 s cold |
| playback-latency-20261102-090423 | Pool alone: warm SC 1.11–1.32 s, but TLS stall still caused 14.91 s |
| playback-latency-20261102-090823 | TLS failover: SC cold first 5.56 s, remaining SC 2.26–2.41 s; still above target |
| playback-latency-20261102-091105 | Extra search removed, short replies consumed: first SC 5.10 s; still above target |
| playback-latency-20261102-091713 | Startup preparation: all 10 launches passed; SC 1.00–3.86 s, YT 0.34–3.57 s |
| playback-latency-20261102-092054 | Reverse layout order, all 14 passed; cold first macOS SC 3.68 s, YT 4.17 s, Deezer 3.37 s |
| playback-latency-20261102-092206 | Copied three user URL-cache rows read-only into scratch profile; all 14 passed, maximum 4.41 s. Parent cleanup initially failed because sqlite context managers do not close connections; corrected with contextlib.closing. |
| playback-latency-20261102-092337 | Separate cold Spotify exposed 8.84 s; this is not hidden by the earlier warm YouTube sample |
| playback-latency-20261102-092923 | Cold Spotify 5.10 s; SDK 3.07 s, remaining preparation still significant |
| playback-latency-20261102-093530 | Visitor-header preparation: cold Spotify 4.93 s, warm 0.21 s; repeat verification continues |
| playback-latency-20261102-093707 | Repetition exposed a 6 s YouTube Music search ReadTimeout; no audio within 20 s. Two subsequent cold runs passed at 4.50 and 4.48 s, so this was intermittent. |
| playback-latency-20261102-094430 / 094441 / 094452 | Requests TLS recovery: three cold Spotify runs passed at 4.76, 4.26 and 4.30 s. |
| playback-latency-20261102-094657 | Separate cold Deezer still took 11.35 s: yt-dlp's HLS manifest request spent 8.03 s in a failed transport operation. |
| playback-latency-20261102-095706 / 095722 / 095732 | SDK TLS recovery: cold Deezer passed at 3.60, 3.54 and 3.55 s; second layout 0.24–0.32 s. |
| playback-latency-20261102-095925 / 100002 | Final two complete passes with three copied user cache rows, both layout orders: 28/28 within 5 s, maximum 4.04 s. |
| playback-latency-20261102-100038 / 100049 | Additional separate cold Spotify 4.46 s and YouTube 3.81 s, plus both warm replays passed. |

An experiment skipping YouTube webpage/config/initial-data requests produced
the same Opus 251 format on one video but authentication failures on two other
public videos. **It was not applied to production.** The diagnostic
`bench_youtube_extract.py` retains this comparison without printing signed URLs.
Global Chrome TLS impersonation was also tested on three public recordings;
it preserved Opus 251 but increased cold extraction time. It was not enabled.

The user confirmed that the actual app opened around 09:20 now starts home and
SoundCloud playlist tracks within five seconds. This is direct evidence for the
reported symptom, alongside the isolated native measurements above.

## Regression checks

The shared transport/cache/startup changes passed the full default suite:
2671 passed, 9 skipped, 1 network test deselected in 102.39 seconds.
The subsequent visitor-header warmup passed 127 targeted playback/provider/
identity tests. The final TLS adapter/SDK changes passed 90 and 40 targeted
tests and all seven real loopback TLS/proxy cases. The final full suite passed
**2678 tests**, with 9 skipped and 1 network test deselected, in 105.16 seconds.
Source inventory, scoped diff whitespace checks and pip check passed.

The final 32-launch cohort had a median of 1.275 seconds and maximum of 4.464
seconds; 24/32 were within the preferred three seconds. At 10:07 Moscow time
the previous user process was already closed. The current code was launched
normally; native NeDotify PID 13180 was responding, visible and not minimized,
and its frontend acknowledged bridge readiness. The real user profile was
preserved.

CPU/GPU/RAM whole-application before/after reduction is not established
by these latency measurements.
