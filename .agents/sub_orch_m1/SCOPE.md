# Scope: Milestone 1 — Audio Playback & Local HTTP Proxy Fixes

## Architecture
Milestone 1 covers the local HTTP audio proxy (`core/proxy.py`), database stream caching (`core/database.py`), app stream re-resolution bridge (`core/app.py`), and frontend HTML5 audio player teardown (`ui/web_new/js/player.js`).

## Feature Inventory
| # | Feature | Description | Target Files |
|---|---------|-------------|--------------|
| 1 | Proxy Socket Abort Resilience | Catch `WinError 10053`, `BrokenPipeError`, `ConnectionResetError` during `wfile.write()` without error logging or crash | `core/proxy.py` |
| 2 | Local File Stream Proxying | Allow local downloaded files in proxy (`file_path`) without SSRF 400 rejection; stream with HTTP 200/206 | `core/proxy.py` |
| 3 | Stream URL TTL & Auto Re-resolution | Reduce stream cache TTL to 3h; perform fast non-blocking re-resolve on 403/410 | `core/proxy.py`, `core/database.py`, `core/app.py` |
| 4 | Range Request & 206 Partial Content | Correct HTTP Range header handling and deliver exact byte ranges with 206 Partial Content | `core/proxy.py` |
| 5 | Frontend Audio Element Teardown | Clear `oldAudio.src` (`oldAudio.removeAttribute('src'); oldAudio.load()`) on pause/fade to prevent background socket leaks | `ui/web_new/js/player.js` |

## Interface Contracts
- URL Format: `http://127.0.0.1:<port>/api/stream?url=<encoded_stream_or_path>&source=<source>&source_id=<id>`
- Response Headers: `Content-Type`, `Accept-Ranges: bytes`, `Content-Range: bytes <start>-<end>/<total>`, `Content-Length: <chunk_len>`
- Disconnect Handling: Proxy suppresses socket errors on aborted connections and stops streaming cleanly without HTTP 500 logs.
- Local File Handling: Proxy accepts local disk paths (`file_path`) and streams directly via `200 OK` or `206 Partial Content`.

## Code Layout
- `core/proxy.py`
- `core/database.py`
- `core/app.py`
- `ui/web_new/js/player.js`
- `tests/test_proxy.py`
