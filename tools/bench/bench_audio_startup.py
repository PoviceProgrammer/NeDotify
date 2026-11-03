"""Compare proxy first-packet latency on an isolated, paced HTTP origin.

This measures the local relay, not live provider resolution or audio decoding.
The legacy adapter reproduces the previous blocking read(32768) behaviour.
"""
import argparse
import http.client
import http.server
import json
import logging
from pathlib import Path
import statistics
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import urllib.parse
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from core import proxy as module


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True)
    parser.add_argument('--repetitions', type=int, default=3)
    args = parser.parse_args()
    logging.basicConfig(level=logging.ERROR)
    payload = b'a' * 65536

    class Origin(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-Type', 'audio/mpeg')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload[:1024])
            self.wfile.flush()
            time.sleep(.15)
            self.wfile.write(payload[1024:])

    class LegacyResponse:
        # The rest of the actual proxy path remains identical in both runs.
        def __init__(self, raw):
            self.raw = raw

        def __getattr__(self, key):
            return getattr(self.raw, key)

        def read1(self, _count):
            return self.raw.read(32768)

    origin = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Origin)
    cache_dir = tempfile.TemporaryDirectory(prefix='nedotify-audio-bench-')
    core = SimpleNamespace(settings=None, youtube=None, soundcloud=None,
                           db=SimpleNamespace(get_cached_stream=lambda *args: None),
                           cache=SimpleNamespace(_streams_dir=cache_dir.name))
    server = module.ThreadingHTTPServer(('127.0.0.1', 0), module.StreamProxyHandler, core, 'bench-token')
    for listener in (origin, server):
        threading.Thread(target=listener.serve_forever, kwargs={'poll_interval': .02}, daemon=True).start()
    original_open, original_safe = module._safe_urlopen, module._is_ssrf_safe_url
    original_cookie_gate = module._host_allows_credentials
    results = {}
    try:
        module._is_ssrf_safe_url = lambda url: True
        # Credentials are absent from this synthetic core.
        module._host_allows_credentials = lambda *args: False
        for mode in ('legacy', 'streaming'):
            def open_fixture(*args, **kwargs):
                raw = urllib.request.urlopen(f'http://127.0.0.1:{origin.server_port}/audio', timeout=3)
                return LegacyResponse(raw) if mode == 'legacy' else raw
            module._safe_urlopen = open_fixture
            results[mode] = {}
            for source in ('youtube', 'soundcloud', 'spotify', 'yandex', 'deezer', 'vk'):
                first_samples, total_samples = [], []
                for _ in range(max(1, args.repetitions)):
                    connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
                    try:
                        query = urllib.parse.urlencode(dict(k='bench-token', source=source,
                                                           url='https://cdn.example/audio'))
                        start = time.perf_counter()
                        connection.request('GET', '/api/stream?' + query)
                        response = connection.getresponse()
                        first = response.read(1024)
                        first_samples.append((time.perf_counter() - start) * 1000)
                        assert response.status == 200 and first + response.read() == payload
                        total_samples.append((time.perf_counter() - start) * 1000)
                    finally:
                        connection.close()
                results[mode][source] = dict(
                    first_packet_median_ms=round(statistics.median(first_samples), 3),
                    total_median_ms=round(statistics.median(total_samples), 3),
                    first_packet_samples_ms=first_samples)
        report = dict(workload='64 KiB HTTP body; first 1 KiB immediate, remainder after 150 ms',
                      repetitions_per_provider=max(1, args.repetitions), results=results)
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report))
    finally:
        module._safe_urlopen, module._is_ssrf_safe_url = original_open, original_safe
        module._host_allows_credentials = original_cookie_gate
        for listener in (server, origin):
            listener.shutdown()
            listener.server_close()
        cache_dir.cleanup()


if __name__ == '__main__':
    main()
