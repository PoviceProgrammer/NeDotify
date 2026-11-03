"""Download and validate one public track in a disposable profile (no UI)."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--provider', choices=('youtube', 'soundcloud', 'deezer', 'spotify'), required=True)
    parser.add_argument('--target', required=True, help='Public provider track ID or supported URL')
    parser.add_argument('--child', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not args.child:
        with tempfile.TemporaryDirectory(prefix='nedotify-download-check-') as folder:
            env = dict(os.environ)
            for key in ('USERPROFILE', 'HOME', 'APPDATA', 'LOCALAPPDATA'):
                env[key] = folder
            try:
                result = subprocess.run([sys.executable, __file__, '--child', '--provider', args.provider,
                                         '--target', args.target], env=env, cwd=ROOT,
                                        capture_output=True, text=True, encoding='utf-8', errors='replace',
                                        timeout=90, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                print(result.stdout.strip())
                if result.returncode:
                    print(re.sub(r'https?://\S+', '<url>', result.stderr[-2000:]))
                return result.returncode
            except subprocess.TimeoutExpired:
                print(json.dumps({'provider': args.provider, 'ok': False, 'error': '90-second deadline'}))
                return 1
    sys.path.insert(0, str(ROOT))
    from core.download_transfer import DownloadContext
    from core.downloader import _downloaded_file_defect
    from services.youtube_service import YouTubeService
    from services.soundcloud_service import SoundCloudService
    from services.deezer_service import DeezerService
    from services.spotify_service import SpotifyService
    providers = {}
    def provider(name):
        if name not in providers:
            providers[name] = {'youtube': YouTubeService, 'soundcloud': SoundCloudService}[name]()
        return providers[name]
    service = DeezerService(providers=provider) if args.provider == 'deezer' else SpotifyService() if args.provider=='spotify' else provider(args.provider)
    start = time.monotonic()
    def checkpoint():
        if time.monotonic() - start > 75:
            raise TimeoutError('Download deadline exceeded')
    context = DownloadContext(1, args.provider, args.target, checkpoint, lambda *args: None)
    try:
        target=args.target
        if args.provider=='spotify' or target.startswith('search:'):
            import threading
            ready=threading.Event();found=[]
            service.search(target.removeprefix('search:'),callback=lambda tracks:(found.extend(tracks),ready.set()),error_callback=lambda error:ready.set())
            if not ready.wait(25) or not found:raise RuntimeError('Provider search returned no tracks')
            selected=found[0];target=selected['source_id']
        if args.provider=='spotify':
            from types import SimpleNamespace
            from core.database import DatabaseManager
            from core.downloader import DownloadManager
            db=DatabaseManager();track_id=db.ensure_track_exists(selected)
            manager=DownloadManager.__new__(DownloadManager)
            manager._core=SimpleNamespace(db=db,settings=None,youtube=provider('youtube'))
            manager._worker_context=threading.local();manager._worker_context.context=context
            try:path=manager._download_spotify_track(target,track_id,os.environ['USERPROFILE'])
            finally:db.close()
        else:
            path = service.download_audio_sync(target, os.environ['USERPROFILE'], download_context=context)
        defect = _downloaded_file_defect(path)
        report = {'provider': args.provider, 'ok': not defect, 'bytes': os.path.getsize(path),
                  'seconds': round(time.monotonic() - start, 2), 'error': defect}
        print(json.dumps(report), flush=True)
        return 1 if defect else 0
    except Exception as exc:
        print(json.dumps({'provider': args.provider, 'ok': False,
                          'seconds': round(time.monotonic() - start, 2),
                          'error': re.sub(r'https?://\S+', '<url>', str(exc))}), flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
