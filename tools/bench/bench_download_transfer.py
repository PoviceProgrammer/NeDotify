"""Repeatable loopback transfer measurement; no user profile or external media.

The 30 ms connection setup delay models a non-local origin. Results describe
this controlled transport workload, never YouTube/SoundCloud CDN throughput.
"""
import argparse
import http.server
import json
from pathlib import Path
import socket
import statistics
import sys
import tempfile
import threading
import time
import tracemalloc

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from core.download_transfer import DownloadContext
from utils import url_safety


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    payload = b'a' * (512 * 1024)
    connections = []

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def setup(self):
            super().setup()
            self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            connections.append(1)
            time.sleep(.03)

        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_args):
            pass

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    original = url_safety._public_addresses
    # Permit exactly the isolated fixture listener, without changing production
    # safety policy or accepting arbitrary private URLs in application code.
    def fixture_addresses(host, port):
        if host == '127.0.0.1' and port == server.server_port:
            return ((socket.AF_INET, socket.SOCK_STREAM, 6, ('127.0.0.1', port)),)
        return original(host, port)
    url_safety._public_addresses = fixture_addresses
    samples, first_bytes = [], []
    tracemalloc.start()
    cpu_start = time.process_time()
    try:
        with tempfile.TemporaryDirectory(prefix='nedotify-transfer-bench-') as folder:
            for index in range(12):
                start = time.perf_counter()
                def progress(downloaded, total):
                    if downloaded and len(first_bytes) == index:
                        first_bytes.append((time.perf_counter() - start) * 1000)
                context = DownloadContext(index, 'fixture', 'fixture', lambda: None, progress)
                context.download_http(f'http://127.0.0.1:{server.server_port}/audio', str(Path(folder) / f'{index}.mp3'))
                samples.append((time.perf_counter() - start) * 1000)
        result = {'workload': 'loopback 512 KiB; 30ms per new connection', 'repetitions': len(samples),
                  'median_startup_ms': round(statistics.median(first_bytes), 3),
                  'median_total_ms': round(statistics.median(samples), 3),
                  'transfer_mib_s': round(6 / (sum(samples) / 1000), 3),
                  'connections': len(connections), 'cpu_seconds': round(time.process_time() - cpu_start, 4),
                  'peak_python_bytes': tracemalloc.get_traced_memory()[1], 'samples_ms': samples}
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps(result))
    finally:
        tracemalloc.stop()
        url_safety._public_addresses = original
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
