"""Bounded live transport probes in a disposable profile; never starts Zapret.

This does not establish native UI playback. Only public metadata, status codes,
content types and byte counts are written; signed stream URLs stay in memory.
"""
import json
import argparse
import os
from pathlib import Path
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--query', default='Rick Astley Never Gonna Give You Up')
    parser.add_argument('--output', default='windows-sources-live-20261109.json')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='nedotify-provider-check-') as profile:
        for key in ('HOME', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA'):
            os.environ[key] = profile
        from services.spotify_service import SpotifyService
        from services.youtube_service import YouTubeService
        from services.soundcloud_service import SoundCloudService
        import requests
        from urllib.parse import urljoin

        def probe_media(url):
            status = {}
            for depth in range(3):
                with requests.get(url, headers={'Range': 'bytes=0-4095'},
                                  timeout=8, stream=True) as response:
                    body = next(response.iter_content(4096), b'')
                    content_type = response.headers.get('Content-Type', '')
                    prefix = 'media' if depth == 0 else 'segment'
                    status[prefix + '_http'] = response.status_code
                    status[prefix + '_type'] = content_type
                    status[prefix + '_bytes'] = len(body)
                    if body.startswith(b'#EXTM3U'):
                        lines = [line.strip() for line in body.decode('utf-8', errors='replace').splitlines()
                                 if line.strip() and not line.startswith('#')]
                        if not lines:
                            break
                        url = urljoin(response.url, lines[0])
                    else:
                        break
            return status

        class Settings:
            def __init__(self):
                self.values = {}

            def get(self, category, key, default=None):
                return self.values.get((category, key), default)

            def set(self, category, key, value):
                self.values[(category, key)] = value

        results = {}
        settings = Settings()
        youtube = YouTubeService(settings)
        services = [('itunes_metadata', SpotifyService(settings)),
                    ('youtube', youtube),
                    ('soundcloud', SoundCloudService(settings))]
        for name, service in services:
            started = time.monotonic()
            done = threading.Event()
            rows, errors = [], []

            def found(items):
                rows.extend(items or [])
                done.set()

            def failed(error):
                errors.append(type(error).__name__)
                done.set()

            service.search(args.query, callback=found,
                           error_callback=failed, **({'limit': 3} if name == 'itunes_metadata' else {'max_results': 3}))
            completed = done.wait(12)
            result = {'search_completed': completed, 'results': len(rows),
                      'search_seconds': round(time.monotonic()-started, 2),
                      'error_types': errors}
            if rows:
                track = rows[0]
                result['first'] = {k: track.get(k) for k in ('title', 'artist', 'duration', 'source')}
                if name != 'itunes_metadata':
                    done.clear()
                    streams = []

                    def stream(url, metadata=None):
                        streams.append(url)
                        done.set()

                    service.get_stream_url(track.get('source_url') or track.get('source_id'),
                                           callback=stream, error_callback=failed)
                    result['stream_completed'] = done.wait(20)
                    result['stream_resolved'] = bool(streams and streams[0])
                    if streams and streams[0]:
                        try:
                            result.update(probe_media(streams[0]))
                        except Exception as exc:
                            result['media_error_type'] = type(exc).__name__
                else:
                    result['audio_provider'] = 'YouTube verified matching, not Spotify audio'
                    from audio.engine import AudioEngine
                    from types import SimpleNamespace
                    engine = AudioEngine()
                    engine.app_core = SimpleNamespace(settings=settings, youtube=youtube)
                    url = engine._resolve_via_network(dict(track))
                    result['verified_youtube_stream'] = bool(url)
                    if url:
                        try:
                            result.update({'mapped_' + key: value for key, value in probe_media(url).items()})
                        except Exception as exc:
                            result['mapped_media_error_type'] = type(exc).__name__
            results[name] = result
            print(json.dumps({name: result}, ensure_ascii=True), flush=True)
        output = ROOT / 'tools/bench/results' / Path(args.output).name
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
        for _, service in services:
            for name in ('_executor', '_playback_executor'):
                executor = getattr(service, name, None)
                if executor is not None:
                    executor.shutdown(wait=True, cancel_futures=True)


if __name__ == '__main__':
    main()
