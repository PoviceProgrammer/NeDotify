"""Compare real yt-dlp playback extraction with optional metadata requests skipped."""
import argparse
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('default', 'audio', 'tls'), required=True)
    parser.add_argument('--id', default='dQw4w9WgXcQ')
    parser.add_argument('--child', action='store_true')
    args = parser.parse_args()
    if not args.child:
        with tempfile.TemporaryDirectory(prefix='nedotify-yt-extract-') as folder:
            env = dict(os.environ)
            for name in ('USERPROFILE', 'HOME', 'APPDATA', 'LOCALAPPDATA'):
                env[name] = folder
            result = subprocess.run([sys.executable, __file__, '--child', '--mode', args.mode, '--id', args.id],
                                    cwd=ROOT, env=env, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=60,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            print(result.stdout.strip())
            return result.returncode
    from core.dns_fallback import install
    install()
    from services.youtube_service import YouTubeService
    from yt_dlp import YoutubeDL
    service = YouTubeService()
    opts = service._get_ydl_opts('bestaudio/best')
    if args.mode == 'audio':
        opts['extractor_args'] = {'youtube': {'player_skip': ['webpage', 'configs', 'initial_data']}}
    elif args.mode == 'tls':
        from yt_dlp.networking.impersonate import ImpersonateTarget
        opts['impersonate'] = ImpersonateTarget(client='chrome')
    stages = []
    start = time.monotonic()
    try:
        with YoutubeDL(opts) as ydl:
            original = ydl.urlopen
            def open_url(request):
                url = request if isinstance(request, str) else request.url
                parsed = urlsplit(url)
                begin = time.monotonic()
                try:
                    return original(request)
                finally:
                    safe_path = parsed.path if parsed.path in ('/watch', '/youtubei/v1/player', '/iframe_api') else '<redacted>'
                    stages.append({'host': parsed.hostname, 'path': safe_path,
                                   'ms': round((time.monotonic() - begin) * 1000)})
            ydl.urlopen = open_url
            info = ydl.extract_info(args.id, download=False)
        print(json.dumps({'mode': args.mode, 'ok': bool(info.get('url')), 'ms': round((time.monotonic()-start)*1000),
                          'audio': {k: info.get(k) for k in ('format_id', 'ext', 'abr', 'acodec', 'duration')},
                          'requests': stages}))
        return 0
    except Exception as exc:
        print(json.dumps({'mode': args.mode, 'ok': False, 'error': type(exc).__name__,
                          'message': re.sub(r'https?://\S+', '<url>', str(exc)), 'requests': stages}))
        return 1
    finally:
        service._executor.shutdown(wait=False, cancel_futures=True)
        service._playback_executor.shutdown(wait=False, cancel_futures=True)


if __name__ == '__main__':
    raise SystemExit(main())
