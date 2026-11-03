# Audio loading, 2026-11-01

The common HTTP audio relay now uses `HTTPResponse.read1(65536)` instead of
`read(32768)`. The latter waited for the entire requested block before forwarding
it. The new path forwards available socket data immediately and preserves byte
order, response headers, range handling, authentication and URL validation.
Responses without `read1` retain the `read` fallback. HLS manifests still use
their separate bounded rewrite path; media segments use the common relay.

Yandex stream extraction requests format metadata first and obtains the signed
link for the selected quality only. Simultaneous requests for the same track and
account/proxy configuration share that work. Yandex, Deezer and VK now have a
bounded playback queue separate from background catalogue/search work. YouTube
and SoundCloud already had their own playback queues. Pool shutdown and test
profile isolation include the new queue.

## Controlled measurement

Run from the Windows project directory:

```powershell
& '.venv_win\Scripts\python.exe' tools/bench/bench_audio_startup.py --out tools/bench/results/audio-startup-20261101.json
```

The real proxy connects to a local synthetic HTTP origin: a 64 KiB body, first
1 KiB sent immediately, remainder after 150 ms. Three repetitions per provider
and mode. The legacy adapter reproduces the previous blocking 32 KiB read while
keeping the remaining proxy path identical. No user database or live credentials
are opened. Full byte equality is checked for every response.

| Source label | Previous first packet, median ms | New first packet, median ms |
|---|---:|---:|
| YouTube | 186.078 | 23.585 |
| SoundCloud | 173.854 | 22.524 |
| Spotify | 168.952 | 2.037 |
| Yandex | 171.049 | 2.475 |
| Deezer | 171.908 | 12.805 |
| VK | 172.285 | 20.699 |

These labels exercise the same common relay with different provider routing.
Differences between rows reflect local scheduling, not provider CDN rankings.
This measures first packet delivery, not live extraction time, audio decoding,
or time until sound. The origin's imposed delay still determines total transfer
time. The change removes the relay's added buffering delay; it cannot increase
the remote service's bandwidth.

## Regression checks

`tests/test_audio_loading_latency.py` holds an upstream's second packet until
the consumer receives the first packet. All six provider paths failed before
the fix and pass afterward. The suite also checks Yandex selecting just one
link for three concurrent callers, playback while every search worker is busy,
and refusal of new playback work after shutdown. In the three-format Yandex
fixture the signed-link request count falls from nine to one without lowering
the selected bitrate.

Run the targeted checks with:

```powershell
& '.venv_win\Scripts\python.exe' -m pytest tests/test_audio_loading_latency.py tests/test_stream_startup_performance.py tests/test_playback_startup_performance.py tests/test_proxy_ranges.py tests/test_proxy_security.py -q
```

Validation: 12 new checks pass; the broader provider/proxy/lifecycle selection
passed 163 tests before the last four concurrency checks were added. The full
suite completed with 2590 passed, 9 skipped, 1 deselected, and one failure:
`test_ui_server.py::test_foreign_origin_cannot_access_ui_or_bridge[headers1]`
received Windows socket abort 10053 instead of an HTTP rejection response.
An immediate repeat of the whole `test_ui_server.py` group passed all 10 tests.
No production server policy was changed to accommodate that abort.
