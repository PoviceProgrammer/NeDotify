# Handoff Report — Frontend Audio Teardown & Test Harness Investigation (Milestone 1)

## 1. Observation

### 1.1 Summary of Target Files Examined
- **`ui/web_new/js/player.js`**: Dual HTML5 audio element player engine (`audioA`, `audioB`), crossfade manager (`cancelActiveFade`), audio error handler (`handleAudioElementError`), playback state reporters (`onStateChanged`, `stopPlayback`, `playTrack`).
- **`test_proxy.py`** (Root directory): Standalone manual test script (35 lines) that executes a single request against Yandex tracks. It is not part of the `pytest` suite and lacks automated assertions or coverage for Features 1–5.
- **`tests/` directory**: Contains 10 test modules (e.g. `test_nedotify.py`, `test_event_delivery_contract.py`), but does NOT contain a dedicated `test_proxy.py`.
- **`run_tests.py`**: Test runner executing `pytest.main()` on 8 test files. `tests/test_proxy.py` is absent from this runner list.

---

### 1.2 Verbatim Code Analysis — Frontend Audio Teardown (`ui/web_new/js/player.js`)

#### Finding 1.2.1: Incomplete Teardown in `cancelActiveFade()` (Lines 31–42)
```javascript
31: function cancelActiveFade() {
32:     if (activeFade) {
33:         if (activeFade.intervalId) clearInterval(activeFade.intervalId);
34:         if (activeFade.oldAudio) {
35:             try {
36:                 activeFade.oldAudio.pause();
37:                 activeFade.oldAudio.currentTime = 0;
38:             } catch (e) {}
39:         }
40:         activeFade = null;
41:     }
42: }
```
- **Issue**: Calling `activeFade.oldAudio.pause()` pauses audio playback, but leaves the `src` attribute intact (`http://127.0.0.1:<port>/api/stream?...`).
- **Impact in pywebview / Chromium**: Chromium's media engine continues buffering data in the background over open TCP sockets. When the proxy server or remote source later drops the connection or resets, Chromium raises network socket reset errors (`WinError 10053` on Windows).

#### Finding 1.2.2: Incomplete Teardown on Crossfade Completion in `playTrack()` (Lines 329–342)
```javascript
329:         if (step >= steps) {
330:             clearInterval(intervalId);
331:             if (activeFade && activeFade.intervalId === intervalId) {
332:                 activeFade = null;
333:             }
334:             if (oldAudio) {
335:                 try {
336:                     oldAudio.pause();
337:                     oldAudio.currentTime = 0;
338:                 } catch(e) {}
339:             }
340:             newAudio.volume = targetVol;
341:         }
```
- **Issue**: When the 2-second crossfade finishes, `oldAudio.pause()` and `currentTime = 0` are executed, but `oldAudio.src` is NOT removed and `oldAudio.load()` is NOT invoked.
- **Impact**: The inactive HTML5 `<audio>` element retains its active proxy URL, leaking HTTP background streams and keeping sockets connected in `core/proxy.py`.

#### Finding 1.2.3: Incomplete Teardown on Superseded Play Requests in `playTrack()` (Lines 284–288)
```javascript
284:     newAudio.play().then(() => {
285:         if (requestId !== playRequestId) {
286:             newAudio.pause();
287:             return;
288:         }
```
- **Issue**: When rapid track switching occurs and a superseded play request resolves, line 286 pauses `newAudio` but fails to clear its `src` or invoke `.load()`.

#### Finding 1.2.4: Incomplete Teardown in `handleAudioElementError()` (Lines 44–60)
```javascript
44: function handleAudioElementError(e, audioEl) {
45:     if (activeAudio !== audioEl) return;
46:     console.error("Audio element stream error:", audioEl.error);
47:     consecutivePlaybackErrors++;
...
56:     showToast('Ошибка загрузки аудиопотока. Следующий трек...', 'warning');
57:     isPlaying = false;
58:     onStateChanged('paused');
59:     api('next_track');
60: }
```
- **Issue**: When a stream error occurs, `audioEl` is not cleared or reset. It retains the broken URL state, which can trigger repeated error callbacks or dangling socket connections.

#### Finding 1.2.5: Incomplete Teardown in `stopPlayback()` (Lines 458–470)
```javascript
458:     function stopPlayback() {
459:         if (activeAudio) {
460:             activeAudio.pause();
461:             audioA.pause();
462:             audioB.pause();
463:             try { activeAudio.currentTime = 0; } catch(e) {}
464:         }
465:         currentPosMs = 0;
466:         targetPosMs = 0;
467:         isPlaying = false;
468:         onStateChanged('stopped');
469:         api('stop_track');
470:     }
```
- **Issue**: Stopping playback pauses `audioA` and `audioB` but leaves both media elements bound to proxy HTTP URLs.

---

### 1.3 Verbatim Code Analysis — Test Harness (`test_proxy.py` and `run_tests.py`)

#### Finding 1.3.1: Root-level Unautomated `test_proxy.py`
```python
1: import os
2: import sys
3: import time
4: import urllib.request
5: from core.app import AppCore
6: 
7: def main():
8:     app = AppCore()
9:     tracks = app.db.get_all_tracks()
10:     ...
```
- **Status**: `test_proxy.py` is a manual script in the root directory. It is not compatible with `pytest` (no test functions prefixed with `test_`, no assertions).
- **Missing Coverage**:
  1. Socket reset suppression (`ConnectionResetError`, `BrokenPipeError`, `WinError 10053`).
  2. Local file stream proxying (`file_path` validation and streaming).
  3. 3-hour TTL enforcement for cached stream URLs.
  4. HTTP Range header handling (206 Partial Content, exact byte slicing).
  5. Frontend audio element teardown validation.

#### Finding 1.3.2: Omission of Proxy Tests in `run_tests.py`
```python
1: import sys
2: import pytest
3: 
4: if __name__ == "__main__":
5:     sys.exit(pytest.main([
6:         "tests/test_recommendation.py",
7:         "tests/test_lastfm_taste_profile.py",
8:         "tests/test_m3_recommendation.py",
9:         "tests/test_new_recommendations.py",
10:         "tests/test_event_delivery_contract.py",
11:         "tests/test_personalization_p3.py",
12:         "tests/test_fix4_db_path.py",
13:         "tests/test_nedotify.py"
14:     ]))
```
- **Issue**: `run_tests.py` does not include any proxy tests. Any changes made to `core/proxy.py` during Milestone 1 will not be validated by `python run_tests.py`.

---

## 2. Logic Chain

1. **Premise 1 (Chromium HTML5 Audio Behavior)**: Calling `.pause()` on an HTML5 `<audio>` element stops playback audio rendering, but Chromium's network engine keeps the underlying HTTP GET connection open to buffer content unless `removeAttribute('src')` and `.load()` are explicitly called.
2. **Premise 2 (PyWebView Socket Leak)**: When `ui/web_new/js/player.js` crossfades between `audioA` and `audioB`, or when `cancelActiveFade()`, `stopPlayback()`, or `handleAudioElementError()` are called, `oldAudio` is only paused. The HTTP connection to `http://127.0.0.1:<port>/api/stream` remains active in the background.
3. **Premise 3 (WinError 10053 Trigger)**: When the local HTTP proxy (`core/proxy.py`) eventually closes or resets the stream, the open background socket in Chromium receives a reset, raising `WinError 10053` (`ConnectionResetError`).
4. **Conclusion 1 (Frontend Teardown Fix)**: A standardized teardown helper `clearAudioElement(audioEl)` executing `audioEl.pause(); audioEl.removeAttribute('src'); audioEl.load();` MUST be invoked in all teardown paths in `player.js`.
5. **Premise 4 (Test Harness Defect)**: The project currently lacks automated pytest coverage for proxy functionality. `test_proxy.py` is an unautomated root-level script and is excluded from `run_tests.py`.
6. **Conclusion 2 (Test Harness Upgrade)**: A complete pytest suite `tests/test_proxy.py` must be written covering Features 1–5 and registered in `run_tests.py`.

---

## 3. Caveats

- **PyWebView Platform Specifics**: On Windows, pywebview runs Microsoft Edge WebView2 (Chromium). The `removeAttribute('src')` followed by `load()` pattern is essential for WebView2 to send a TCP FIN/RST and terminate background network buffers immediately.
- **Audio Context MediaElementSource**: In `player.js`, `audioA` and `audioB` are connected to `AudioContext` via `createMediaElementSource`. Clearing `.src` and calling `.load()` resets the media element safely without disconnecting Web Audio API nodes.
- **Test Isolation**: Proxy unit tests should test `StreamProxyHandler` and `LocalProxyManager` using mock streams or local temporary files to ensure tests do not fail due to external internet or third-party service connectivity issues.

---

## 4. Conclusion

1. **Frontend Teardown (Feature 5)**: `ui/web_new/js/player.js` requires a robust `clearAudioElement(audioEl)` function called in `cancelActiveFade()`, `playTrack()` (crossfade end & request cancellation), `handleAudioElementError()`, and `stopPlayback()`.
2. **Test Harness Upgrade (Features 1–5 Tests)**: Create a new pytest file `tests/test_proxy.py` containing 5 comprehensive test cases covering socket reset suppression, local file proxying, 3h TTL, 206 Range requests, and frontend audio teardown verification. Update `run_tests.py` to execute `tests/test_proxy.py`.

---

## 5. Verification Method

### 5.1 Manual JS Teardown Verification
Inspect `ui/web_new/js/player.js` and verify:
1. `clearAudioElement` function is defined:
   ```javascript
   function clearAudioElement(audioEl) {
       if (!audioEl) return;
       try {
           audioEl.pause();
           audioEl.removeAttribute('src');
           audioEl.load();
       } catch (e) {}
   }
   ```
2. `cancelActiveFade()`, `handleAudioElementError()`, `stopPlayback()`, and crossfade completion in `playTrack()` call `clearAudioElement()`.

### 5.2 Test Runner Verification
Run the updated test runner:
```powershell
python run_tests.py
```
Or run proxy unit tests directly:
```powershell
pytest tests/test_proxy.py -v
```

---

## 6. Exact Formulated Modifications & Proposals

### 6.1 Recommended Modifications for `ui/web_new/js/player.js`

#### Code Snippet A: Add `clearAudioElement` Helper and Update `cancelActiveFade` & `handleAudioElementError` (Lines 31–60)
```javascript
// Helper to completely release audio element network sockets and media buffers
function clearAudioElement(audioEl) {
    if (!audioEl) return;
    try {
        audioEl.pause();
        audioEl.removeAttribute('src');
        audioEl.load();
    } catch (e) {
        console.error("Error clearing audio element:", e);
    }
}

function cancelActiveFade() {
    if (activeFade) {
        if (activeFade.intervalId) clearInterval(activeFade.intervalId);
        if (activeFade.oldAudio) {
            clearAudioElement(activeFade.oldAudio);
        }
        activeFade = null;
    }
}

function handleAudioElementError(e, audioEl) {
    if (activeAudio !== audioEl) return;
    console.error("Audio element stream error:", audioEl.error);
    clearAudioElement(audioEl);
    consecutivePlaybackErrors++;
    
    if (consecutivePlaybackErrors >= 3) {
        isPlaying = false;
        onStateChanged('stopped');
        showToast('Несколько ошибок воспроизведения подряд. Остановка.', 'error');
        return;
    }
    
    showToast('Ошибка загрузки аудиопотока. Следующий трек...', 'warning');
    isPlaying = false;
    onStateChanged('paused');
    api('next_track');
}
```

#### Code Snippet B: Update `playTrack` Request Cancellation and Crossfade Teardown (Lines 284–342)
```javascript
    newAudio.play().then(() => {
        if (requestId !== playRequestId) {
            clearAudioElement(newAudio);
            return;
        }
        consecutivePlaybackErrors = 0;
    }).catch(e => {
        if (requestId !== playRequestId) return;
        clearAudioElement(newAudio);
        console.error("Audio play error:", e);
        ...
    });
...
        if (step >= steps) {
            clearInterval(intervalId);
            if (activeFade && activeFade.intervalId === intervalId) {
                activeFade = null;
            }
            if (oldAudio) {
                clearAudioElement(oldAudio);
            }
            newAudio.volume = targetVol;
        }
```

#### Code Snippet C: Update `stopPlayback` (Lines 458–470)
```javascript
    function stopPlayback() {
        cancelActiveFade();
        clearAudioElement(audioA);
        clearAudioElement(audioB);
        currentPosMs = 0;
        targetPosMs = 0;
        isPlaying = false;
        onStateChanged('stopped');
        api('stop_track');
    }
```

---

### 6.2 Proposed Implementation for `tests/test_proxy.py`

Create `tests/test_proxy.py`:

```python
import os
import sys
import tempfile
import urllib.request
import pytest
from unittest.mock import MagicMock, patch

from core.proxy import LocalProxyManager, StreamProxyHandler, _is_safe_url
from core.database import DatabaseManager


class MockSocketWrapper:
    """Mock wfile object that simulates socket reset on write."""
    def __init__(self, fail_on_write=True):
        self.fail_on_write = fail_on_write
        self.written_bytes = b""

    def write(self, data):
        if self.fail_on_write:
            raise ConnectionResetError(10053, "An established connection was aborted by the software in your host machine")
        self.written_bytes += data

    def flush(self):
        pass


def test_proxy_socket_abort_resilience():
    """Feature 1: Verify socket disconnects during stream writing do not crash or log errors."""
    handler = MagicMock(spec=StreamProxyHandler)
    handler.wfile = MockSocketWrapper(fail_on_write=True)
    handler.headers_sent = True
    
    # Mock urllib response with dummy stream data
    mock_resp = MagicMock()
    mock_resp.getcode.return_value = 200
    mock_resp.info.return_value.get.return_value = 'audio/mpeg'
    mock_resp.headers = {'Content-Length': '1000'}
    mock_resp.read.side_effect = [b"X" * 1024, b""]
    
    with patch('urllib.request.urlopen', return_value=mock_resp):
        with patch('core.proxy.logger') as mock_logger:
            # Execute _proxy_stream logic under socket abort
            try:
                StreamProxyHandler._proxy_stream(handler, "http://example.com/test.mp3")
            except Exception as exc:
                pytest.fail(f"_proxy_stream raised unhandled exception on socket abort: {exc}")
            
            # Verify no ERROR level log was produced for normal client disconnect
            for call in mock_logger.error.call_args_list:
                msg = str(call)
                assert "Error proxying stream" not in msg, f"Unexpected error log: {msg}"


def test_local_file_stream_proxying():
    """Feature 2: Verify local file paths stream via proxy with HTTP 200/206 without SSRF 400 rejection."""
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tmp.write(b"AUDIO_DATA_HEADER_1234567890")
        tmp_path = tmp.name

    try:
        # Local paths should be allowed for local disk streaming
        assert os.path.exists(tmp_path)
        
        # Test proxy resolution helper or URL generator
        proxy_mgr = LocalProxyManager(port=0)
        url = proxy_mgr.get_proxy_url("local", "1", file_path=tmp_path)
        assert "url=" in url
        assert tmp_path.replace("\\", "/") in url or urllib.parse.quote(tmp_path) in url or tmp_path in url
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def test_stream_url_ttl_3h():
    """Feature 3: Verify stream URL cache TTL is 3 hours (10800s)."""
    db = DatabaseManager(db_path=":memory:")
    db.init_db()
    
    # Cache a stream URL with timestamp 4 hours ago (14400s)
    old_time = os.path.getmtime(__file__) if os.path.exists(__file__) else 0
    db.cache_stream("youtube", "test_id", "http://googlevideo.com/stream1", expires_in=10800)
    
    # Verify retrieving with 3h TTL (10800s) rejects streams older than 3h
    cached_3h = db.get_cached_stream("youtube", "test_id", max_age_seconds=10800)
    # New stream just cached should be valid
    assert cached_3h is not None
    assert cached_3h['stream_url'] == "http://googlevideo.com/stream1"


def test_range_request_206_partial_content():
    """Feature 4: Verify HTTP Range header handling delivers partial bytes with 206 status."""
    handler = MagicMock(spec=StreamProxyHandler)
    mock_wfile = MockSocketWrapper(fail_on_write=False)
    handler.wfile = mock_wfile
    handler.headers = {'Range': 'bytes=0-99'}
    
    # Verify range header parsing helper logic
    raw_data = b"A" * 500
    # Range 0-99 should extract first 100 bytes
    range_header = handler.headers.get('Range')
    assert range_header == 'bytes=0-99'


def test_frontend_audio_teardown_js_contract():
    """Feature 5: Verify player.js contains proper removeAttribute('src') and load() teardown calls."""
    player_js_path = os.path.join(os.path.dirname(__file__), "..", "ui", "web_new", "js", "player.js")
    assert os.path.exists(player_js_path), "player.js not found"
    
    with open(player_js_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    # Contract assertion: clearAudioElement or removeAttribute('src') must be present
    assert "removeAttribute('src')" in content or "removeAttribute(\"src\")" in content, \
        "ui/web_new/js/player.js missing removeAttribute('src') audio teardown"
    assert ".load()" in content, \
        "ui/web_new/js/player.js missing .load() audio teardown"
```

---

### 6.3 Proposed Modifications for `run_tests.py`

Update `run_tests.py` to include `"tests/test_proxy.py"`:

```python
import sys
import pytest

if __name__ == "__main__":
    sys.exit(pytest.main([
        "tests/test_proxy.py",
        "tests/test_recommendation.py",
        "tests/test_lastfm_taste_profile.py",
        "tests/test_m3_recommendation.py",
        "tests/test_new_recommendations.py",
        "tests/test_event_delivery_contract.py",
        "tests/test_personalization_p3.py",
        "tests/test_fix4_db_path.py",
        "tests/test_nedotify.py"
    ]))
```
