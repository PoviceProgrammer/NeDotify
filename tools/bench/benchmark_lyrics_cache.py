r"""Reproducible offline microbenchmark; no app launch or real profile access.

From the repository root in PowerShell:
    & ".venv_win\Scripts\python.exe" tools/bench/benchmark_lyrics_cache.py

The upstream is a mock delayed by 150 ms. Results measure cache overhead/reuse,
not the speed or availability of real LRCLIB/Netease/Genius servers.
"""
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from services.lyrics_service import LyricsService  # noqa: E402

PROVIDERS = ('lrclib', 'netease', 'qqmusic', 'genius', 'megalobiz')


def measure(function):
    started = time.perf_counter()
    assert function()['status'] == 'found'
    return (time.perf_counter() - started) * 1000


def main():
    cold, first_event, memory, disk = [], [], [], []
    calls = []
    with tempfile.TemporaryDirectory(prefix='nedotify-lyrics-benchmark-') as directory:
        path = Path(directory) / 'lyrics.db'
        service = LyricsService(cache_path=path)
        for name in PROVIDERS:
            setattr(service._lookup, name, lambda *args: None)
        def provider(context, *args):
            calls.append(1)
            time.sleep(.15)
            return service._lookup.accept(context, context['metadata']['title'],
                       context['metadata']['artists'], context['duration'],
                       '[00:01.00] Hello', 'Hello', 'Controlled provider')
        service._lookup.lrclib = provider
        for number in range(7):
            title = f'Benchmark Song {number}'
            started, received = time.perf_counter(), []
            def update(payload):
                if payload.get('status') == 'found' and not received:
                    received.append((time.perf_counter() - started) * 1000)
            cold.append(measure(lambda: service.get_lyrics(title, 'Benchmark Artist', 120000, on_update=update)))
            first_event.append(received[0])
            memory.append(measure(lambda: service.get_lyrics(title, 'Benchmark Artist', 120000)))
            reopened = LyricsService(cache_path=path)
            def forbidden(*args):
                calls.append('unexpected network')
                raise AssertionError('Disk hit must not contact a provider')
            for name in PROVIDERS:
                setattr(reopened._lookup, name, forbidden)
            disk.append(measure(lambda: reopened.get_lyrics(title, 'Benchmark Artist', 120000)))
        assert calls == [1] * 7
        med = lambda values: round(statistics.median(values), 3)
        print(json.dumps({'controlled_upstream_delay_ms': 150, 'samples': 7,
            'median_first_lyrics_event_ms': med(first_event),
            'median_cold_complete_including_disk_write_ms': med(cold),
            'median_ram_ms': med(memory), 'median_disk_after_restart_ms': med(disk),
            'provider_calls': len(calls), 'cache_db_bytes': path.stat().st_size}, indent=2))


if __name__ == '__main__':
    main()

