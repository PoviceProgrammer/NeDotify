"""Live metadata-only album audit in a temporary, credential-free profile.

Run with .venv_win/Scripts/python.exe; this never starts playback or Zapret.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'docs/audits/windows-album-live-after-2026-11-09.json')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='nedotify-album-audit-') as folder:
        for key in ('HOME', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA'):
            os.environ[key] = folder
        from services.youtube_service import YouTubeService
        from services.spotify_service import SpotifyService
        from services.deezer_service import DeezerService
        from services.catalog_service import CatalogService
        from services.base_service import BaseMusicService
        settings = SimpleNamespace(get=lambda category, key, default=None: default)
        youtube, apple, deezer = YouTubeService(settings), SpotifyService(settings), DeezerService(settings)
        catalog = CatalogService(youtube, settings)
        report = {'date': '2026-11-09', 'query': 'Coldplay Parachutes',
                  'profile': 'temporary, no credentials', 'sources': []}
        try:
            for source, provider in [('youtube', youtube), ('itunes_legacy_spotify', apple), ('deezer', deezer)]:
                event, box = threading.Event(), {}
                started = time.monotonic()
                provider.search(report['query'], result_type='albums',
                    callback=lambda rows, box=box, event=event: (box.update(rows=rows), event.set()),
                    error_callback=lambda error, box=box, event=event: (box.update(error=str(error)), event.set()))
                complete = event.wait(12)
                entry = {'source': source, 'completed': complete,
                         'search_ms': round((time.monotonic() - started) * 1000)}
                if box.get('error'):
                    entry['search_error'] = box['error']
                rows = box.get('rows', [])
                entry['search_count'] = len(rows)
                chosen = next((row for row in rows if 'parachutes' in str(row.get('title', '')).lower()
                               and 'coldplay' in str(row.get('artist', '')).lower()), None)
                if chosen:
                    details = catalog.album_details(chosen)
                    entry.update(album={key: chosen.get(key) for key in ('source_id', 'title', 'artist', 'year', 'cover_url')},
                        status=details.get('status'), track_count=len(details.get('tracks') or []),
                        details_error=details.get('error'),
                        durations_known=sum(bool(track.get('duration')) for track in details.get('tracks') or []))
                    entry['verified_album'] = {key: (details.get('album') or {}).get(key)
                        for key in ('title', 'artist', 'year', 'release_date', 'album_type', 'cover_url')}
                    cached_at = time.monotonic()
                    cached = catalog.album_details(chosen)
                    entry['cached_ms'] = round((time.monotonic() - cached_at) * 1000, 2)
                    entry['cached_track_count'] = len(cached.get('tracks') or [])
                report['sources'].append(entry)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps(report, ensure_ascii=True))
        finally:
            youtube._executor.shutdown(wait=True, cancel_futures=True)
            youtube._playback_executor.shutdown(wait=True, cancel_futures=True)
            apple._executor.shutdown(wait=True, cancel_futures=True)
            BaseMusicService.shutdown_executor()


if __name__ == '__main__':
    main()
