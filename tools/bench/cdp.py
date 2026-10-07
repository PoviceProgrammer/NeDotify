"""Chrome DevTools Protocol client for NeDotify benchmarks and the visual guard.

Standard library only: the project forbids new dependencies, and a full
WebSocket implementation for text frames is ~150 lines. Verified against
WebView2 154.0.4258.53 (CDP 1.3) on this machine.

Entry point for the benchmark is ``connect()``: it polls
``http://127.0.0.1:<port>/json/list`` until the app's page target shows up.
"""

from __future__ import annotations

import base64
import json
import os
import socket
import struct
import threading
import time
import urllib.request
from urllib.parse import urlparse

__all__ = ["CDPError", "WSClient", "CDPSession", "wait_for_page_target"]

DEFAULT_DEBUG_PORT = 9222


class CDPError(RuntimeError):
    pass


# --------------------------------------------------------------------------
# Minimal RFC6455 client (text frames, client-side masking, no extensions)
# --------------------------------------------------------------------------
class WSClient:
    def __init__(self, url: str, timeout: float = 20.0):
        u = urlparse(url)
        if u.scheme != "ws":
            raise CDPError(f"only ws:// supported, got {u.scheme!r}")
        self.host = u.hostname or "127.0.0.1"
        self.port = u.port or 80
        self.path = u.path + (("?" + u.query) if u.query else "")
        self.timeout = timeout
        self._sock: socket.socket | None = None
        self._buf = b""
        self._lock = threading.Lock()
        self._id = 0
        self._pending: dict[int, dict] = {}
        self._events: list[dict] = []
        self._closed = False

    def connect(self) -> "WSClient":
        s = socket.create_connection((self.host, self.port), timeout=self.timeout)
        s.settimeout(self.timeout)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        s.sendall((
            f"GET {self.path} HTTP/1.1\r\n"
            f"Host: {self.host}:{self.port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        ).encode("ascii"))
        while b"\r\n\r\n" not in self._buf:
            chunk = s.recv(4096)
            if not chunk:
                raise CDPError("connection closed during handshake")
            self._buf += chunk
        head, _, rest = self._buf.partition(b"\r\n\r\n")
        self._buf = rest
        status = head.split(b"\r\n", 1)[0].decode("latin-1", "replace")
        if "101" not in status:
            raise CDPError(f"handshake failed: {status}")
        self._sock = s
        threading.Thread(target=self._recv_loop, daemon=True).start()
        return self

    def __enter__(self) -> "WSClient":
        return self.connect()

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        self._closed = True
        if self._sock:
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def _recv_exact(self, n: int) -> bytes:
        while len(self._buf) < n:
            chunk = self._sock.recv(65536)
            if not chunk:
                raise CDPError("socket closed mid-frame")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def _send_frame(self, payload: bytes, opcode: int = 0x1) -> None:
        header = bytearray([0x80 | opcode])
        n = len(payload)
        header.append(0x80 | (n if n < 126 else 126 if n < (1 << 16) else 127))
        if n >= 126:
            header += struct.pack("!H", n) if n < (1 << 16) else struct.pack("!Q", n)
        mask = os.urandom(4)
        header += mask
        self._sock.sendall(bytes(header) + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))

    def _recv_loop(self) -> None:
        try:
            while not self._closed:
                b0, b1 = self._recv_exact(2)
                opcode = b0 & 0x0F
                masked = b1 & 0x80
                length = b1 & 0x7F
                if length == 126:
                    length = struct.unpack("!H", self._recv_exact(2))[0]
                elif length == 127:
                    length = struct.unpack("!Q", self._recv_exact(8))[0]
                mask = self._recv_exact(4) if masked else None
                data = self._recv_exact(length) if length else b""
                if mask:
                    data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
                if opcode == 0x8:
                    break
                if opcode == 0x9:
                    self._send_frame(data, opcode=0xA)
                    continue
                if opcode not in (0x0, 0x1, 0x2):
                    continue
                try:
                    msg = json.loads(data.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    continue
                with self._lock:
                    if "id" in msg:
                        self._pending[msg["id"]] = msg
                    else:
                        self._events.append(msg)
        except (OSError, CDPError, struct.error):
            pass
        finally:
            self._closed = True

    def call(self, method: str, params: dict | None = None, timeout: float | None = None) -> dict:
        if self._sock is None:
            raise CDPError("not connected")
        with self._lock:
            self._id += 1
            mid = self._id
        self._send_frame(json.dumps({"id": mid, "method": method, "params": params or {}}).encode("utf-8"))
        deadline = time.monotonic() + (timeout or self.timeout)
        while time.monotonic() < deadline:
            with self._lock:
                if mid in self._pending:
                    return self._pending.pop(mid)
            if self._closed:
                raise CDPError(f"connection closed while waiting for {method}")
            time.sleep(0.002)
        raise CDPError(f"timeout waiting for {method}")

    def drain_events(self, max_events: int = 5000) -> list[dict]:
        with self._lock:
            out, self._events = self._events[:max_events], self._events[max_events:]
        return out

    def wait_event(self, method: str, timeout: float = 10.0) -> dict | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                for i, e in enumerate(self._events):
                    if e.get("method") == method:
                        return self._events.pop(i)
            time.sleep(0.005)
        return None

    def evaluate(self, expression: str, timeout: float = 15.0,
                 await_promise: bool = False):
        res = self.call("Runtime.evaluate", {
            "expression": expression,
            "awaitPromise": await_promise,
            "returnByValue": True,
        }, timeout=timeout)
        details = res.get("exceptionDetails")
        if details:
            raise CDPError(f"JS exception: {json.dumps(details)[:400]}")
        return res.get("result", {}).get("result", {}).get("value")


# --------------------------------------------------------------------------
# CDP session with the NeDotify-specific conveniences
# --------------------------------------------------------------------------
class CDPSession:
    def __init__(self, ws: WSClient):
        self.ws = ws
        self.console: list[dict] = []
        self.errors: list[dict] = []

    @classmethod
    def attach(cls, port: int = DEFAULT_DEBUG_PORT, timeout: float = 60.0,
               url_filter: str | None = None) -> "CDPSession":
        url = wait_for_page_target(port, timeout=timeout, url_filter=url_filter)
        ws = WSClient(url, timeout=40.0).connect()
        s = cls(ws)
        s.ws.call("Runtime.enable")
        s.ws.call("Page.enable")
        try:
            s.ws.call("Performance.enable")
        except CDPError:
            pass
        return s

    def close(self) -> None:
        self.ws.close()

    def __enter__(self) -> "CDPSession":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- lifecycle helpers -------------------------------------------------
    def freeze_animations(self) -> None:
        """Stop every CSS/WAAPI animation at its current time.

        Combined with a deterministic fixture this makes goldens byte-stable;
        verified: two captures 0.7 s apart were byte-identical.
        """
        self.ws.call("Animation.enable")
        self.ws.call("Animation.setPlaybackRate", {"playbackRate": 0})

    def set_viewport(self, width: int, height: int, dpr: int) -> None:
        self.ws.call("Emulation.setDeviceMetricsOverride", {
            "width": width, "height": height,
            "deviceScaleFactor": dpr, "mobile": False,
        })

    def screenshot_png(self) -> bytes:
        res = self.ws.call("Page.captureScreenshot",
                           {"format": "png", "captureBeyondViewport": False},
                           timeout=40.0)
        data = res.get("result", {}).get("data")
        if not data:
            raise CDPError(f"captureScreenshot returned no data: {json.dumps(res)[:300]}")
        return base64.b64decode(data)

    # -- page helpers ------------------------------------------------------
    def js(self, expression: str, timeout: float = 15.0, await_promise: bool = False):
        return self.ws.evaluate(expression, timeout=timeout, await_promise=await_promise)

    def wait_for_js(self, expression: str, timeout: float = 30.0,
                    interval: float = 0.05) -> float:
        """Poll a JS predicate; return seconds waited (0.0 if immediately true)."""
        t0 = time.monotonic()
        deadline = t0 + timeout
        while time.monotonic() < deadline:
            try:
                if self.js(f"!!({expression})", timeout=5.0):
                    return time.monotonic() - t0
            except CDPError:
                pass
            time.sleep(interval)
        raise TimeoutError(f"JS condition never became true within {timeout}s: {expression}")

    def wait_for_new_document(self, previous_time_origin: float,
                              timeout: float = 60.0) -> float:
        """Block until a *fresh* document has committed.

        Essential after ``Page.reload``: polling straight away races the
        navigation and happily reads the outgoing document, where app state
        such as ``window._nedotifyInitialized`` is still true. That silently
        turned "time to interactive" into "time to call CDP".

        Returns the new ``performance.timeOrigin``.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                origin = self.js("performance.timeOrigin", timeout=5.0)
                if isinstance(origin, (int, float)) and abs(origin - previous_time_origin) > 0.5:
                    return origin
            except CDPError:
                pass          # context destroyed mid-navigation: expected
            time.sleep(0.01)
        raise TimeoutError("new document never committed after reload")

    def perf_metrics(self) -> dict:
        res = self.ws.call("Performance.getMetrics", timeout=15.0)
        return {m["name"]: m["value"] for m in res.get("result", {}).get("metrics", [])}

    def install_event_recorder(self) -> None:
        """Record every console error and python event name into the page."""
        self.js("""
        (() => {
          if (window.__bench) return;
          window.__bench = { consoleErrors: [], pythonEvents: [] };
          const origError = console.error.bind(console);
          console.error = function(...a) {
            try { window.__bench.consoleErrors.push(a.map(String).join(' ')); } catch (e) {}
            return origError(...a);
          };
          const origWarn = console.warn.bind(console);
          console.warn = function(...a) {
            try { window.__bench.consoleErrors.push('WARN ' + a.map(String).join(' ')); } catch (e) {}
            return origWarn(...a);
          };
          const origEmit = window.onPythonEvent;
          if (typeof origEmit === 'function') {
            window.onPythonEvent = function(name, payload) {
              try { window.__bench.pythonEvents.push({ name: String(name), t: performance.now() }); } catch (e) {}
              return origEmit.apply(this, arguments);
            };
          }
          return true;
        })()
        """)


def _fetch_json(port: int, path: str, timeout: float = 2.0):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def wait_for_page_target(port: int = DEFAULT_DEBUG_PORT, timeout: float = 60.0,
                         url_filter: str | None = None) -> str:
    """Poll /json/list until a page target exists; return its webSocketDebuggerUrl.

    Retries: the very first launch of a brand-new profile spends several seconds
    creating the WebView2 user-data folder, during which the debugging endpoint
    either is not listening yet or accepts the socket without answering. A
    plain timed-out HTTP read must therefore not abort the run.
    """
    t0 = time.monotonic()
    deadline = t0 + timeout
    attempts = 0
    last: Exception | None = None
    while time.monotonic() < deadline:
        attempts += 1
        try:
            for t in _fetch_json(port, "/json/list"):
                if t.get("type") != "page":
                    continue
                ws_url = t.get("webSocketDebuggerUrl")
                if not ws_url:
                    continue
                if url_filter and url_filter not in (t.get("url") or ""):
                    continue
                return ws_url
            last = CDPError("list had no matching page target")
        except Exception as e:
            last = e
        time.sleep(0.2)
    raise TimeoutError(
        f"no CDP page target on :{port} within {timeout}s "
        f"({attempts} attempts, last error: {last!r})"
    )
