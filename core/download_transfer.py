"""Cooperative transfer control shared by the download providers."""

import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from uuid import uuid4
from urllib.parse import urljoin

from utils.url_safety import is_safe_media_url, guarded_requests_get


YTDLP_WORKER_ARG = '--yt-dlp-download-worker'


def run_bundled_ytdlp(args):
    """Use the packaged yt-dlp CLI with the worker's redirected streams."""
    if sys.platform == 'win32' and sys.stdout is None:
        import ctypes
        import msvcrt
        from ctypes import wintypes

        get_handle = ctypes.WinDLL('kernel32', use_last_error=True).GetStdHandle
        get_handle.argtypes = (wintypes.DWORD,)
        get_handle.restype = wintypes.HANDLE
        sys.stdin = open(os.devnull, encoding='utf-8')
        for name, handle in (('stdout', -11), ('stderr', -12)):
            fd = msvcrt.open_osfhandle(get_handle(handle), os.O_WRONLY | os.O_BINARY)
            setattr(sys, name, os.fdopen(fd, 'w', encoding='utf-8', errors='replace', line_buffering=True))

    from yt_dlp import main
    return main(args)


class DownloadInterrupted(Exception):
    pass


class IncompleteDownload(IOError):
    retryable = True


class InvalidRange(ValueError):
    """Reject a response before touching the existing, validated partial."""


class DownloadContext:
    def __init__(self, track_id, source, source_id, checkpoint, progress, settings=None, *, probe=False):
        digest = hashlib.sha256(f'{source}:{source_id}'.encode('utf-8')).hexdigest()[:16]
        safe_track_id = re.sub(r'[^a-zA-Z0-9_-]', '_', str(track_id))
        self.stem = f'download_{safe_track_id}_{digest}'
        self.checkpoint = checkpoint
        self.progress = progress
        self.settings = settings
        self.probe = probe

    @classmethod
    def standalone(cls, source, source_id, settings):
        return cls(uuid4().hex, source, source_id, lambda: None, lambda done, total: None, settings)

    def download_executable(self, target, output_dir, *, youtube=True, authenticated=False):
        """Port of Riff's CLI transfer. The queue processes the native audio."""
        from core.download_processing import run_tool
        self.checkpoint()
        tools = getattr(self, 'tools', {})
        binary = tools.get('yt_dlp_path')
        if binary:
            args = [binary]
        elif getattr(sys, 'frozen', False):
            args = [sys.executable, YTDLP_WORKER_ARG]
        else:
            args = [sys.executable, '-m', 'yt_dlp']

        policy = getattr(self, 'policy', None)
        fmt = getattr(policy, 'format', 'source')
        audio = 'bestaudio' if youtube else 'bestaudio[format_id!*=preview]'
        formats = [f'{audio}[ext={fmt}]'] if fmt in ('m4a', 'mp3', 'opus') else []
        if youtube:
            from utils.audio_validation import ffprobe_path
            if not ffprobe_path():
                formats.extend(f'{audio}[ext={ext}]' for ext in ('m4a', 'mp3', 'opus', 'ogg') if ext != fmt)
        formats.append(audio)
        template = os.path.join(os.path.abspath(output_dir).replace('%', '%%'), self.stem + '_%(id)s.%(ext)s')
        args += ['--ignore-config', '--no-playlist', '--no-warnings', '--newline', '--progress',
                '--encoding', 'utf-8', '--continue', '--no-overwrites', '--abort-on-unavailable-fragments',
                '--concurrent-fragments', str(getattr(policy, 'fragment_concurrency', 2)),
                '--progress-template', 'download:nd-progress:%(progress.downloaded_bytes)s:%(progress.total_bytes,progress.total_bytes_estimate)s',
                '--print', 'after_move:nd-file:%(filepath)s', '-f', '/'.join(formats),
                '-o', template]
        if self.probe:
            args += ['--socket-timeout', '4', '--retries', '0', '--extractor-retries', '0',
                     '--fragment-retries', '0', '--proxy', '', '--no-cache-dir']
        else:
            args += ['--socket-timeout', '10', '--retries', '2', '--extractor-retries', '1',
                     '--fragment-retries', '2']
        if tools.get('ffmpeg_path'):
            args += ['--ffmpeg-location', os.path.dirname(tools['ffmpeg_path'])]
        if youtube:
            args += ['--force-ipv4', '--http-chunk-size', '1M']
            node = shutil.which('node')
            if node:
                args += ['--js-runtimes', f'node:{node}']
        if self.settings:
            from services.base_service import normalize_proxy_url
            proxy = normalize_proxy_url(self.settings.get('auth', 'proxy_url', ''))
            if proxy:
                args += ['--proxy', proxy]
        result = []

        def line(text):
            self.checkpoint()
            if text.startswith('nd-progress:'):
                parts = text.split(':')
                try:
                    self.progress(int(float(parts[1])), int(float(parts[2])) if parts[2] not in ('NA', 'None') else 0)
                except (ValueError, IndexError):
                    pass
            elif text.startswith('nd-file:'):
                result[:] = [text[len('nd-file:'):]]
        browser = self.settings.get('auth', 'browser_cookies', 'none') if authenticated and youtube and self.settings else None
        cookies = self.settings.get('auth', 'cookies_file_path', '') if authenticated and self.settings else None
        if browser and browser != 'none':
            run_tool([*args, '--cookies-from-browser', str(browser), '--', target],
                     self.checkpoint, timeout=600, on_line=line)
        elif cookies and os.path.isfile(cookies):
            # yt-dlp writes its jar on exit. Give each child its own copy.
            with tempfile.TemporaryDirectory(prefix='nedotify-cookies-') as temporary:
                jar = os.path.join(temporary, 'cookies.txt')
                shutil.copyfile(cookies, jar)
                run_tool([*args, '--cookies', jar, '--', target], self.checkpoint, timeout=600, on_line=line)
        else:
            run_tool([*args, '--', target], self.checkpoint, timeout=600, on_line=line)
        if not result:
            raise IOError('yt-dlp не вернул аудиофайл')
        path = os.path.realpath(result[0])
        if (os.path.normcase(os.path.dirname(path)) != os.path.normcase(os.path.realpath(output_dir))
                or not os.path.basename(path).startswith(self.stem + '_')):
            raise ValueError('yt-dlp вернул неверный путь аудиофайла')
        if not os.path.isfile(path):
            raise IncompleteDownload('yt-dlp не создал аудиофайл')
        if os.path.getsize(path) == 0:
            os.remove(path)
            raise IncompleteDownload('yt-dlp вернул пустой аудиофайл')
        return path

    def download_http(self, url, output_path):
        """Resume a validated partial response, or restart when Range is unsupported."""
        self.checkpoint()
        partial_path = output_path + '.part'
        metadata_path = partial_path + '.json'
        metadata = {}
        try:
            with open(metadata_path, encoding='utf-8') as metadata_file:
                metadata = json.load(metadata_file)
        except (OSError, ValueError, TypeError):
            pass
        if not isinstance(metadata, dict):
            metadata = {}
        offset = os.path.getsize(partial_path) if os.path.isfile(partial_path) else 0
        validator = metadata.get('etag') or metadata.get('last_modified')
        headers = {'Accept-Encoding': 'identity'}
        if offset and validator:
            headers.update({'Range': f'bytes={offset}-', 'If-Range': validator})
        else:
            offset = 0
        response = None
        try:
            for redirect_count in range(6):
                self.checkpoint()
                if not is_safe_media_url(url):
                    raise ValueError('Unsafe media URL rejected')
                response = guarded_requests_get(url, headers=headers, stream=True,
                                        timeout=(5, 5), allow_redirects=False)
                if response.status_code not in (301, 302, 303, 307, 308):
                    break
                location = response.headers.get('Location')
                response.close()
                response = None
                if not location or redirect_count == 5:
                    raise ValueError('Слишком много перенаправлений загрузки')
                url = urljoin(url, location)
            if response.status_code == 416:
                response.close()
                headers.pop('Range', None)
                headers.pop('If-Range', None)
                response = guarded_requests_get(url, headers=headers, stream=True,
                                        timeout=(5, 5), allow_redirects=False)
                offset = 0
            response.raise_for_status()
            if response.status_code not in (200, 206):
                raise ValueError('Источник вернул неполный ответ загрузки')
            if response.status_code == 206:
                content_range = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)',
                                             response.headers.get('Content-Range', ''))
                if not content_range or int(content_range.group(1)) != offset:
                    raise InvalidRange('Источник вернул неверный диапазон загрузки')
                total = int(content_range.group(3))
                if not offset <= int(content_range.group(2)) < total:
                    raise InvalidRange('Источник вернул неверный диапазон загрузки')
                response_validator = response.headers.get('ETag') or response.headers.get('Last-Modified')
                if offset and response_validator and response_validator != validator:
                    for p in (partial_path, metadata_path):
                        try:
                            if os.path.isfile(p):
                                os.remove(p)
                        except OSError:
                            pass
                    raise ValueError('Источник изменил файл во время загрузки. Повторите загрузку.')
            else:
                offset = 0
                total = int(response.headers.get('Content-Length') or 0)
            metadata = {
                'etag': response.headers.get('ETag', ''),
                'last_modified': response.headers.get('Last-Modified', ''),
            }
            with open(metadata_path, 'w', encoding='utf-8') as metadata_file:
                json.dump(metadata, metadata_file)
            downloaded = offset
            self.progress(downloaded, total)
            with open(partial_path, 'ab' if offset else 'wb') as audio_file:
                for chunk in response.iter_content(chunk_size=128 * 1024):
                    self.checkpoint()
                    if chunk:
                        audio_file.write(chunk)
                        downloaded += len(chunk)
                        self.progress(downloaded, total)
            self.checkpoint()
            if not total:
                # No declared length: a successful EOF alone cannot prove an
                # audio stream is complete. Verify its decoded container.
                from utils.audio_validation import audio_duration
                if audio_duration(partial_path) <= 0:
                    raise IOError('Источник не подтвердил полноту аудиофайла')
            if total and downloaded != total:
                raise IncompleteDownload('Соединение прервано до завершения загрузки')
            os.replace(partial_path, output_path)
            try:
                os.remove(metadata_path)
            except OSError:
                pass
            self.progress(downloaded, total or downloaded)
            return output_path
        except Exception as exc:
            if not os.path.isfile(partial_path) or (isinstance(exc, (ValueError, PermissionError)) and not isinstance(exc, InvalidRange)):
                for p in (partial_path, metadata_path):
                    try:
                        if os.path.isfile(p):
                            os.remove(p)
                    except OSError:
                        pass
            raise
        finally:
            if response is not None:
                response.close()
