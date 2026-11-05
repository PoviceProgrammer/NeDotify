"""Cooperative transfer control shared by the download providers."""

import hashlib
import json
import os
import re
from urllib.parse import urljoin

from utils.url_safety import is_safe_media_url, guarded_requests_get


class DownloadInterrupted(Exception):
    pass


class IncompleteDownload(IOError):
    retryable = True


class InvalidRange(ValueError):
    """Reject a response before touching the existing, validated partial."""


class DownloadContext:
    def __init__(self, track_id, source, source_id, checkpoint, progress):
        digest = hashlib.sha256(f'{source}:{source_id}'.encode('utf-8')).hexdigest()[:16]
        safe_track_id = re.sub(r'[^a-zA-Z0-9_-]', '_', str(track_id))
        self.stem = f'download_{safe_track_id}_{digest}'
        self.checkpoint = checkpoint
        self.progress = progress

    def ydl_options(self, output_dir):
        self.checkpoint()
        options = {
            'outtmpl': os.path.join(output_dir, self.stem + '_%(id)s.%(ext)s'),
            'continuedl': True,
            'overwrites': False,
            'nopart': False,
            # Never publish an apparently successful file with missing HLS/DASH
            # fragments. Keep the partial and let the queue retry/resume it.
            'skip_unavailable_fragments': False,
            'progress_hooks': [self._ydl_progress],
            'concurrent_fragment_downloads': getattr(getattr(self, 'policy', None), 'fragment_concurrency', 2),
            'buffersize': 256 * 1024,
            'http_chunk_size': 10 * 1024 * 1024,
            'socket_timeout': 10,
            'retries': 2,
            'fragment_retries': 2,
            'extractor_retries': 1,
        }
        tools = getattr(self, 'tools', {}) or {}
        if tools.get('ffmpeg_path'):
            options['ffmpeg_location'] = os.path.dirname(tools['ffmpeg_path'])
        # Prefer the requested native container before considering a transcode.
        fmt = getattr(getattr(self, 'policy', None), 'format', 'source')
        if fmt in ('m4a', 'mp3', 'opus'):
            options['format'] = f'bestaudio[ext={fmt}]/bestaudio/best'
        return options

    def _ydl_progress(self, data):
        self.checkpoint()
        self.progress(
            data.get('downloaded_bytes') or 0,
            data.get('total_bytes') or data.get('total_bytes_estimate') or 0,
        )

    def download_executable(self, target, output_dir):
        """Use Setup's official verified binary when the module is unavailable."""
        from core.download_processing import run_tool
        options = self.ydl_options(output_dir)
        binary = self.tools.get('yt_dlp_path')
        if not binary:
            raise RuntimeError('yt-dlp не найден. Восстановите компоненты в настройках.')
        args = [binary, '--no-playlist', '--no-warnings', '--newline', '--progress',
                '--continue', '--no-overwrites', '--socket-timeout', '10', '--retries', '2',
                '--fragment-retries', '2', '--abort-on-unavailable-fragments',
                '--concurrent-fragments', str(options['concurrent_fragment_downloads']),
                '--progress-template', 'download:nd-progress:%(progress.downloaded_bytes)s:%(progress.total_bytes,progress.total_bytes_estimate)s',
                '--print', 'after_move:nd-file:%(filepath)s', '-f', options.get('format', 'bestaudio/best'),
                '-o', options['outtmpl']]
        if options.get('ffmpeg_location'):
            args += ['--ffmpeg-location', options['ffmpeg_location']]
        settings = getattr(self, 'settings', None)
        if settings:
            from services.base_service import normalize_proxy_url
            proxy = normalize_proxy_url(settings.get('auth', 'proxy_url', ''))
            if proxy:
                args += ['--proxy', proxy]
            cookies = settings.get('auth', 'cookies_file_path', '')
            if cookies and os.path.isfile(cookies):
                args += ['--cookies', cookies]
            browser = settings.get('auth', 'browser_cookies', 'none')
            if browser and browser != 'none':
                args += ['--cookies-from-browser', str(browser)]
        args += ['--', target]
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
        run_tool(args, self.checkpoint, timeout=600, on_line=line)
        if not result:
            raise IOError('yt-dlp не вернул аудиофайл')
        path = os.path.realpath(result[0])
        if os.path.dirname(path) != os.path.realpath(output_dir) or not os.path.basename(path).startswith(self.stem):
            raise ValueError('yt-dlp вернул неверный путь аудиофайла')
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
