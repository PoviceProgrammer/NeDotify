"""Real YouTube -> AppApi -> DownloadManager -> validated audio, scratch profile.

Does not start/stop Zapret or alter VPN, routes, cookies or the real library.
Only safe metadata and file integrity evidence are retained; media is removed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import uuid
from types import SimpleNamespace

ROOT = Path(os.environ.get('NEDOTIFY_AUDIT_ROOT') or Path(__file__).resolve().parents[2])
if not getattr(sys, 'frozen', False):
    sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-id', default='dQw4w9WgXcQ')
    parser.add_argument('--duration', type=float, default=213)
    parser.add_argument('--timeout', type=float, default=150)
    args = parser.parse_args()
    clean_pc = os.environ.get('NEDOTIFY_AUDIT_CLEAN_PC') == '1'
    if clean_pc:
        os.environ['PATH'] = os.pathsep.join([os.path.join(os.environ.get('SystemRoot', r'C:\Windows'), 'System32'), os.environ.get('SystemRoot', r'C:\Windows')])
    output = ROOT / 'tools/bench/results' / ('youtube-download-audit-' + time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:6] + '.json')
    with tempfile.TemporaryDirectory(prefix='nedotify-youtube-audit-') as folder:
        for key in ('HOME', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA'):
            os.environ[key] = folder
        from core.api import AppApi
        from core.database import DatabaseManager
        from core.downloader import DownloadManager
        from core.setup_engine import SetupEngine
        from services.youtube_service import YouTubeService
        from utils.audio_validation import audio_duration

        class Settings:
            def __init__(self):
                self.values = {('auth', 'browser_cookies'): 'none',
                               ('downloads', 'format'): 'source',
                               ('downloads', 'embed_cover'): False}
            def get(self, category, key, default=None):
                return self.values.get((category, key), default)
            def set(self, category, key, value):
                self.values[category, key] = value

        settings = Settings()
        if clean_pc:
            settings.set('downloads', 'format', 'mp3')
        db = DatabaseManager(str(Path(folder) / 'audit.db'))
        youtube = YouTubeService(settings)
        core = SimpleNamespace(db=db, settings=settings, youtube=youtube,
                               resolver=None, setup=SetupEngine(settings))
        preparation = None
        if clean_pc:
            initial = core.setup.get_status(deep=True)
            started_setup = core.setup.start_repair()
            if not started_setup.get('success'):
                raise RuntimeError('Clean-PC repair did not start')
            deadline = time.monotonic() + 240
            while core.setup.get_status()['updating'] and time.monotonic() < deadline:
                time.sleep(.25)
            prepared = core.setup.get_status(deep=True)
            preparation = {'initialReady': initial['ready'], 'ready': prepared['ready'],
                           'operation': prepared['operation']['status'],
                           'dependencies': {k: {'available': v['available'], 'source': v['source']} for k,v in prepared['dependencies'].items()}}
            if not prepared['ready']:
                raise RuntimeError('Clean-PC preparation failed: ' + str(prepared['operation'].get('error')))
        api = AppApi.__new__(AppApi)
        api._core = core
        terminal = threading.Event()
        events = []
        def emit(name, data=None):
            events.append((name, data))
            if name in ('download_complete', 'download_failed'):
                terminal.set()
        api._emit = emit
        core.api = api
        manager = DownloadManager(core)
        core.downloader = manager
        started = time.monotonic()
        result = {'vpnModified': False, 'profileIsolated': True, 'cookiesUsed': False,
                  'sourceId': args.source_id, 'path': 'AppApi.download_track -> DownloadManager -> YouTubeService'}
        import importlib.util
        loader = type(importlib.util.find_spec('core.api').loader).__name__
        result.update(frozenRuntime=bool(getattr(sys, 'frozen', False)), apiModuleLoader=loader,
                      setupLeaseEnabled=True, restrictedPath=clean_pc, preparation=preparation)
        if result['frozenRuntime'] and 'Frozen' not in loader:
            raise RuntimeError('Audit must load product modules from the frozen archive')
        try:
            result['accepted'] = api.download_track({'source': 'youtube', 'source_id': args.source_id,
                'title': 'YouTube audit recording', 'artist': 'Audit', 'duration': args.duration})
            result['terminalEventReceived'] = terminal.wait(args.timeout)
            complete = [data for name, data in events if name == 'download_complete']
            result['completeEvents'] = len(complete)
            result['failedEvents'] = sum(name == 'download_failed' for name, _ in events)
            if complete:
                row = db.get_track(complete[0]['track_id'])
                path = Path(row['file_path'])
                result.update(databaseDownloaded=bool(row['is_downloaded']), fileBytes=path.stat().st_size,
                              duration=round(audio_duration(str(path)), 3),
                              extension=path.suffix, sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                              queueStatus=db.download_queue_get_status(row['id']))
                if clean_pc:
                    import miniaudio
                    info = miniaudio.get_file_info(str(path))
                    stream = miniaudio.stream_file(str(path), sample_rate=info.sample_rate, nchannels=info.nchannels)
                    try:
                        result['nativeDecodeFrames'] = sum(len(samples) // info.nchannels for samples in stream)
                    finally:
                        stream.close()
                    result['nativeDecodeRate'] = info.sample_rate
                    assert result['nativeDecodeFrames'] > info.sample_rate
                    assert path.suffix == '.mp3'
                result['ok'] = bool(result['databaseDownloaded'] and result['queueStatus'] == 'completed'
                                    and result['fileBytes'] > 10000
                                    and (not args.duration or abs(result['duration'] - args.duration) < 10))
            else:
                result['ok'] = False
                result['errorCodes'] = [data.get('code') for name, data in events
                                        if name == 'download_failed' and isinstance(data, dict)]
        finally:
            manager.stop(drain_timeout=8)
            core.setup.close()
            youtube.shutdown_executor()
            db.close()
        result['seconds'] = round(time.monotonic() - started, 2)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
        print(json.dumps({'artifact': str(output), **result}, ensure_ascii=True), flush=True)
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
