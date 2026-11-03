"""Bounded anonymous SC provider -> real transfer -> ffprobe/decode diagnostic.

All media and transient state stay in TEMP. Signed URLs are held in memory;
the report includes only public source id, status, protocol, bytes and timings.
"""
from __future__ import annotations
import contextlib
import io
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
REPORT = ROOT / 'tools' / 'bench' / 'results' / ('sc-tun-path-' + time.strftime('%Y%m%d-%H%M%S') + '.json')
scratch = Path(tempfile.mkdtemp(prefix='nedotify-sc-tun-'))
for key in ('HOME', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA'):
    os.environ[key] = str(scratch)
logging.disable(logging.CRITICAL)
REPORT_DATA = {}


class Settings:
    def get(self, category, key, default=None):
        if category == 'auth':
            return 'none' if key == 'browser_cookies' else ''
        if category == 'services' and key == 'youtube_enabled':
            return False
        return default


class SilentLogger:
    def debug(self, *args): pass
    def warning(self, *args): pass
    def error(self, *args): pass


def run():
    from core.dns_fallback import install
    install()
    from services.soundcloud_service import SoundCloudService
    from core.download_transfer import DownloadContext
    from core.downloader import _downloaded_file_defect
    from utils.audio_validation import audio_duration
    from utils.url_safety import guarded_open_url
    import yt_dlp
    started = time.monotonic()
    report = REPORT_DATA
    report.update(source='soundcloud', source_id='2393146779', anonymous=True,
                  youtube_fallback_enabled=False, status='failed', valid=False, phase='resolve')
    done = threading.Event(); result = {}
    service = SoundCloudService(Settings())
    def success(url, info):
        result.update(url=url, info=info); done.set()
    def failure(message):
        result['error_type'] = 'provider_callback_failure'; done.set()
    service.get_stream_url(report['source_id'], callback=success, error_callback=failure)
    if not done.wait(35):
        report['error_type'] = 'resolve_deadline_35s'
        return report
    report['resolve_ms'] = round((time.monotonic() - started) * 1000)
    if not result.get('url'):
        report.update(error_type=result.get('error_type', 'missing_stream'))
        return report
    url = result['url']; expected_duration = result['info'].get('duration', 0)
    report['expected_duration'] = expected_duration
    cached_id = service._get_ydl().cache.load('soundcloud', 'client_id')
    import re
    report['ydl_cached_client_id_valid'] = isinstance(cached_id, str) and bool(re.fullmatch('[A-Za-z0-9]{32}', cached_id))
    if report['ydl_cached_client_id_valid']:
        t = time.monotonic()
        try:
            response = service._session.get('https://api-v2.soundcloud.com/tracks/' + report['source_id'], params={'client_id': cached_id}, timeout=4)
            report['cached_id_api_status'] = response.status_code
        except Exception as error:
            report['cached_id_api_error_type'] = type(error).__name__
        report['cached_id_api_ms'] = round((time.monotonic() - t) * 1000)
    report['phase'] = 'range'
    t = time.monotonic()
    with guarded_open_url(urllib.request.Request(url, headers={'Range': 'bytes=0-65535'}), timeout=4) as response:
        head = response.read(65536)
        report.update(range_status=response.status, range_bytes=len(head))
    report['range_ms'] = round((time.monotonic() - t) * 1000)
    is_hls = head.lstrip().startswith(b'#EXTM3U')
    report['protocol'] = 'hls' if is_hls else 'http'
    report['phase'] = 'transfer'
    deadline = time.monotonic() + 60
    def checkpoint():
        if time.monotonic() > deadline:
            raise TimeoutError('transfer diagnostic deadline')
    context = DownloadContext('diagnostic', 'soundcloud', report['source_id'], checkpoint, lambda *args: None)
    t = time.monotonic()
    if is_hls:
        options = context.ydl_options(str(scratch))
        options.update(quiet=True, no_warnings=True, logger=SilentLogger(), noplaylist=True)
        with yt_dlp.YoutubeDL(options) as ydl:
            info = {'id': report['source_id'], 'title': 'route diagnostic', 'url': url,
                    'ext': 'm4a', 'protocol': 'm3u8_native'}
            ydl.process_info(info)
            filename = ydl.prepare_filename(info)
    else:
        filename = context.download_http(url, str(scratch / 'diagnostic.mp3'))
    report['transfer_ms'] = round((time.monotonic() - t) * 1000)
    report['bytes'] = Path(filename).stat().st_size
    report['phase'] = 'validation'
    defect = _downloaded_file_defect(filename, expected_duration)
    report['app_container_validator_accepts'] = not bool(defect)
    probe = subprocess.run([shutil.which('ffprobe'), '-v', 'error', '-count_packets',
                            '-show_entries', 'format=format_name,duration:stream=codec_name,nb_read_packets',
                            '-of', 'json', filename], capture_output=True, text=True, timeout=12)
    data = json.loads(probe.stdout)
    report['duration'] = float(data['format']['duration'])
    report['codec'] = data['streams'][0]['codec_name']
    report['audio_packets'] = int(data['streams'][0]['nb_read_packets'])
    report['container_valid'] = probe.returncode == 0 and report['audio_packets'] > 0 and abs(report['duration'] - expected_duration) < 5
    ffmpeg = shutil.which('ffmpeg')
    t = time.monotonic()
    decode = subprocess.run([ffmpeg, '-v', 'error', '-i', filename, '-t', '1', '-f', 'null', '-'], capture_output=True, timeout=15)
    report['decode_1s_ms'] = round((time.monotonic() - t) * 1000)
    report['decode_1s_valid'] = decode.returncode == 0
    report['valid'] = report['container_valid'] and report['decode_1s_valid']
    report['status'] = 'passed' if report['valid'] else 'failed'
    report['total_ms'] = round((time.monotonic() - started) * 1000)
    report['phase'] = 'complete'
    return report


if __name__ == '__main__':
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            report = run()
    except Exception as error:
        report = dict(REPORT_DATA)
        report.update(status='failed', valid=False, error_type=type(error).__name__)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({'report': str(REPORT), 'data': report}), flush=True)
    os._exit(0 if report.get('valid') else 1)
