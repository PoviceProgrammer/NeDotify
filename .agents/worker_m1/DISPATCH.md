## 2026-08-07T15:32:05Z
You are the Worker for Milestone 1: Audio Playback & Local HTTP Proxy Fixes in AURA Music.
Your Working Directory: c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/.agents/worker_m1

Mandatory Inputs:
1. Read ORIGINAL_REQUEST.md at: c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/.agents/ORIGINAL_REQUEST.md
2. Read PROJECT.md at: c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/PROJECT.md
3. Read SCOPE.md at: c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/.agents/sub_orch_m1/SCOPE.md
4. Read Explorer 1 Handoff at: c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/.agents/explorer_m1_1/handoff.md
5. Read Explorer 2 Handoff at: c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/.agents/explorer_m1_2/handoff.md
6. Read Explorer 3 Handoff at: c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/.agents/explorer_m1_3/handoff.md

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Your Tasks:
1. Update `core/proxy.py`:
   - Feature 1: Define `CLIENT_DISCONNECT_ERRORS = (ConnectionResetError, BrokenPipeError, ConnectionAbortedError, socket.error, OSError)`. Suppress socket disconnection errors during `self.wfile.write(chunk)` and socket operations in `_proxy_stream()` and `_serve_local_file()` so client disconnects log `logger.debug` and break loop cleanly without error logs or calling `send_error(500)`.
   - Feature 2: Support local file streaming in `_is_local_file()`, `_find_playable_url()`, and `do_GET()`. If `real_url` is a local disk file (`os.path.exists`), stream via `_serve_local_file(real_url)` with HTTP 200/206 without SSRF HTTP(S) domain rejection.
   - Feature 3: In `_find_playable_url()`, pass `max_age_seconds=10800` (3 hours) to `get_cached_stream()`. In `_proxy_stream()`, on HTTP 401/403/404/410 upstream errors, purge stale stream record from `stream_cache` table before retrying re-resolution. In `_resolve_stream_url()`, reduce `event.wait(timeout=16.0)` to `event.wait(timeout=3.5)`.
   - Feature 4: Implement Range request parsing (`_parse_range_header`) and 206 Partial Content delivery in `_serve_local_file()` and `_proxy_stream()` with proper `Content-Range: bytes start-end/total`, `Content-Length`, and `Accept-Ranges: bytes` headers.

2. Update `core/database.py`:
   - Feature 3: In `get_cached_stream()` (line 737), change default `max_age_seconds` parameter from `86400` to `10800` (3 hours).

3. Update `ui/web_new/js/player.js`:
   - Feature 5: Implement `clearAudioElement(audioEl)` function executing `audioEl.pause(); audioEl.removeAttribute('src'); audioEl.load();`. Invoke `clearAudioElement()` in `cancelActiveFade()`, `handleAudioElementError()`, `stopPlayback()`, and crossfade completion / cancelled play request in `playTrack()`.

4. Create `tests/test_proxy.py` and update `run_tests.py`:
   - Create automated pytest module `tests/test_proxy.py` with tests for Features 1–5: `test_proxy_socket_abort_resilience`, `test_local_file_stream_proxying`, `test_stream_url_ttl_3h`, `test_range_request_206_partial_content`, `test_frontend_audio_teardown_js_contract`.
   - Update `run_tests.py` to include `"tests/test_proxy.py"`.

5. Verification:
   - Run tests using command: `python run_tests.py`
   - Verify all tests pass with 100% success rate.
   - Document test command, output, modified file paths, and verification results in your handoff report at:
     `c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/.agents/worker_m1/handoff.md`
   - Send completion message to parent when done.
