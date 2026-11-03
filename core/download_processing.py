"""Output policy, cancellable postprocessing and tags for the existing queue.

Architectural reference: Riff v43.2.2 src/server/server.js handleDownload:
reuse verified audio, explicit output format, embed metadata, publish on success.
Implementation is native Python; no Electron or second download manager.
"""
from dataclasses import dataclass
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import shutil


class ToolExecutionError(RuntimeError):
    def __init__(self, returncode, diagnostic):
        match = re.search(r'(?i)HTTP(?: Error)?\s+(\d{3})', diagnostic)
        self.code = int(match.group(1)) if match else None
        self.retryable = self.code in (408, 429, 500, 502, 503, 504) or any(
            text in diagnostic.lower() for text in ('timed out', 'connection reset', 'temporary failure'))
        super().__init__(f'Источник вернул HTTP {self.code}' if self.code else f'Аудиокомпонент завершился с кодом {returncode}')


@dataclass(frozen=True)
class OutputPolicy:
    format: str = 'source'
    quality: str = 'best'
    max_concurrent: int = 2
    fragment_concurrency: int = 2
    embed_metadata: bool = True
    embed_cover: bool = True

    @classmethod
    def from_settings(cls, settings):
        def get(key, default):
            return settings.get('downloads', key, default) if settings else default
        def bounded(key, default):
            try:
                return max(1, min(4, int(get(key, default))))
            except (ValueError, TypeError):
                return default
        fmt = str(get('format', 'source')).lower()
        quality = str(get('quality', 'best'))
        return cls(fmt if fmt in ('source', 'mp3', 'm4a', 'opus', 'flac', 'wav') else 'source',
                   quality if quality in ('best', '128', '192', '256', '320') else 'best',
                   bounded('max_concurrent', 2), bounded('fragment_concurrency', 2),
                   bool(get('embed_metadata', True)), bool(get('embed_cover', True)))


def download_directory(settings=None):
    configured = settings.get('downloads', 'directory', '') if settings else ''
    path = os.path.expanduser(str(configured or '~/.nedotify/downloads'))
    if not os.path.isabs(path):
        raise ValueError('Укажите абсолютный путь папки скачивания')
    return os.path.realpath(path)


def safe_filename(track, track_id):
    """Readable Windows-safe names with a stable database identity suffix."""
    label = ' - '.join(str(track.get(key) or '').strip() for key in ('artist', 'title')).strip(' -')
    label = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', label).rstrip(' .')[:130].rstrip(' .') or 'Track'
    if label.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}:
        label = '_' + label
    identity = re.sub(r'[^\w-]', '_', str(track_id), flags=re.ASCII)
    return f'{label} [{identity}]'


def run_tool(args, checkpoint, timeout=300, on_line=None):
    """Bound output memory and kill only the process tree owned by this task."""
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    with tempfile.TemporaryFile() as diagnostic:
        process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE if on_line else diagnostic, stderr=diagnostic,
                                   creationflags=flags, text=bool(on_line), encoding='utf-8' if on_line else None,
                                   errors='replace' if on_line else None)
        errors = []
        reader = None
        if on_line:
            import threading
            def consume():
                try:
                    for line in iter(lambda: process.stdout.readline(65536), ''):
                        on_line(line.rstrip())
                except Exception as exc:
                    errors.append(exc)
                finally:
                    process.stdout.close()
            reader = threading.Thread(target=consume, name='download_tool_output', daemon=True)
            reader.start()
        started = time.monotonic()
        try:
            while process.poll() is None:
                checkpoint()
                if errors:
                    raise errors[0]
                if time.monotonic() - started > timeout:
                    raise TimeoutError('Обработка аудио превысила допустимое время')
                time.sleep(.05)
            checkpoint()
            if reader:
                reader.join(timeout=2)
            if errors:
                raise errors[0]
            if process.returncode:
                # Do not return ffmpeg output: it can contain signed media URLs.
                diagnostic.seek(0, os.SEEK_END)
                size = diagnostic.tell()
                diagnostic.seek(max(0, size - 4096))
                raise ToolExecutionError(process.returncode, diagnostic.read().decode('utf-8', errors='replace'))
        finally:
            if process.poll() is None:
                if os.name == 'nt':
                    subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=flags, timeout=5, check=False)
                else:
                    process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
            if reader:
                reader.join(timeout=2)


def fetch_cover(track, checkpoint):
    """Bounded optional artwork read; no credentials or temporary cover files."""
    from utils.url_safety import guarded_open_url, safe_public_url
    import urllib.request
    checkpoint()
    value = str(track.get('cover_path') or track.get('cover_url') or track.get('cover') or track.get('thumbnail') or '')
    if not value:
        return None
    limit = 8 * 1024 * 1024
    try:
        if value.startswith(('data:image/png;base64,', 'data:image/jpeg;base64,', 'data:image/webp;base64,')):
            import base64
            encoded = value.split(',', 1)[1]
            if len(encoded) > limit * 4 // 3 + 4:
                return None
            data = base64.b64decode(encoded, validate=True)
        elif value.startswith(('https://', 'http://')):
            if not safe_public_url(value):
                return None
            with guarded_open_url(urllib.request.Request(value), timeout=5) as response:
                data = response.read(limit + 1)
        elif os.path.isfile(value) and os.path.getsize(value) <= limit:
            data = Path(value).read_bytes()
        else:
            return None
        checkpoint()
        if len(data) > limit:
            return None
        if data.startswith(b'\xff\xd8\xff'):
            return data, 'image/jpeg'
        if data.startswith(b'\x89PNG\r\n\x1a\n'):
            return data, 'image/png'
        if data.startswith(b'RIFF') and data[8:12] == b'WEBP':
            from PIL import Image
            import io
            with Image.open(io.BytesIO(data)) as image:
                if image.width * image.height > 16_000_000:
                    return None
                output = io.BytesIO()
                image.convert('RGB').save(output, format='JPEG', quality=90)
                if output.tell() <= limit:
                    return output.getvalue(), 'image/jpeg'
    except Exception as error:
        # Artwork is optional; corrupt images or an unavailable decoder must
        # not turn a complete audio transfer into a failed download.
        from core.download_transfer import DownloadInterrupted
        if isinstance(error, DownloadInterrupted):
            raise
        return None
    return None


def embed_tags(path, track, cover=None):
    """Fill missing metadata, retaining existing correct tags and native audio."""
    from mutagen import File
    from mutagen.id3 import ID3, TIT2, TPE1, TALB, TCON, TDRC, TRCK, TXXX, APIC
    from mutagen.mp4 import MP4, MP4Cover
    from mutagen.flac import FLAC, Picture
    from mutagen.oggopus import OggOpus
    from mutagen.oggvorbis import OggVorbis
    from mutagen.mp3 import MP3
    from mutagen.wave import WAVE
    import base64
    audio = File(path)
    if audio is None or not isinstance(audio, (MP3, WAVE, MP4, FLAC, OggOpus, OggVorbis)):
        return 'Контейнер источника не поддерживает встроенные теги без FFmpeg'
    if audio.tags is None:
        audio.add_tags()
    values = {'title': track.get('title'), 'artist': track.get('artist'), 'album': track.get('album'),
              'genre': track.get('genre'), 'date': track.get('year'), 'tracknumber': track.get('track_number'),
              'source': f"{track.get('source', '')}:{track.get('source_id', '')}"}
    values = {key: str(value) for key, value in values.items() if value not in (None, '', 'Unknown Artist', 'Unknown Album')}
    if isinstance(audio.tags, ID3):
        frames = {'title': TIT2, 'artist': TPE1, 'album': TALB, 'genre': TCON, 'date': TDRC, 'tracknumber': TRCK}
        for key, frame in frames.items():
            if key in values and not audio.tags.getall(frame.__name__):
                audio.tags.add(frame(encoding=3, text=values[key]))
        if not audio.tags.getall('TXXX:SOURCE'):
            audio.tags.add(TXXX(encoding=3, desc='SOURCE', text=values.get('source', '')))
        if cover and not audio.tags.getall('APIC'):
            audio.tags.add(APIC(encoding=3, mime=cover[1], type=3, desc='Cover', data=cover[0]))
    elif isinstance(audio, MP4):
        for key, atom in {'title': '\xa9nam', 'artist': '\xa9ART', 'album': '\xa9alb', 'genre': '\xa9gen', 'date': '\xa9day'}.items():
            if key in values and not audio.tags.get(atom):
                audio.tags[atom] = [values[key]]
        if values.get('tracknumber') and not audio.tags.get('trkn'):
            try:
                audio.tags['trkn'] = [(int(values['tracknumber'].split('/')[0]), 0)]
            except ValueError:
                pass
        audio.tags.setdefault('----:com.apple.iTunes:SOURCE', [values.get('source', '').encode()])
        if cover and not audio.tags.get('covr'):
            audio.tags['covr'] = [MP4Cover(cover[0], imageformat=MP4Cover.FORMAT_PNG if cover[1] == 'image/png' else MP4Cover.FORMAT_JPEG)]
    elif isinstance(audio, (FLAC, OggOpus, OggVorbis)):
        for key, value in values.items():
            if not audio.tags.get(key):
                audio.tags[key] = [value]
        if cover and not getattr(audio, 'pictures', None) and not audio.tags.get('metadata_block_picture'):
            picture = Picture()
            picture.type, picture.mime, picture.data = 3, cover[1], cover[0]
            if isinstance(audio, FLAC):
                audio.add_picture(picture)
            else:
                audio.tags['metadata_block_picture'] = [base64.b64encode(picture.write()).decode('ascii')]
    else:
        return 'Контейнер источника не поддерживает встроенные теги'
    audio.save()
    return ''


def process_download(path, track, policy, context, directory, cover=None):
    """Do at most one codec operation, then atomically publish a unique file."""
    source_ext = Path(path).suffix.lower().lstrip('.')
    if os.path.realpath(os.path.dirname(path)) != os.path.realpath(directory) or not os.path.basename(path).startswith(context.stem):
        staging = os.path.join(directory, context.stem + '.source.' + source_ext)
        shutil.copyfile(path, staging)
        path = staging
    ext = source_ext if policy.format == 'source' else policy.format
    tools = getattr(context, 'tools', {}) or {}
    warnings = []
    work = path
    temporary = os.path.join(directory, context.stem + '.processing.' + ext)
    published = False
    metadata_written = False
    try:
        if policy.format == 'flac' and source_ext not in ('flac', 'wav'):
            raise ValueError('FLAC доступен только для lossless-источника. Выберите оригинал или формат сжатия.')
        reduce_bitrate = False
        if policy.format != 'source' and policy.quality != 'best' and ext in ('mp3', 'm4a', 'opus'):
            try:
                from mutagen import File
                source_info = File(path)
                reduce_bitrate = getattr(getattr(source_info, 'info', None), 'bitrate', 0) > int(policy.quality) * 1100
            except (OSError, ValueError):
                pass
        if policy.format != 'source' and (ext != source_ext or reduce_bitrate):
            ffmpeg = tools.get('ffmpeg_path')
            if not ffmpeg:
                raise RuntimeError('FFmpeg не найден. Восстановите компоненты в настройках.')
            codec = {'mp3': 'libmp3lame', 'm4a': 'aac', 'opus': 'libopus', 'flac': 'flac', 'wav': 'pcm_s16le'}[ext]
            # AAC and Opus may only need a container change, not another lossy encode.
            copy = not reduce_bitrate and ((ext == 'm4a' and source_ext in ('aac', 'mp4')) or (ext == 'opus' and source_ext in ('ogg', 'webm') and _is_opus(path)))
            args = [ffmpeg, '-nostdin', '-y', '-i', path, '-map', '0:a:0', '-vn', '-c:a', 'copy' if copy else codec]
            if not copy and ext in ('mp3', 'm4a', 'opus'):
                args += ['-b:a', (policy.quality if policy.quality != 'best' else ('192' if ext == 'opus' else '320')) + 'k']
            args += [temporary]
            run_tool(args, context.checkpoint)
            work = temporary
        elif policy.embed_metadata and ext == 'webm' and tools.get('ffmpeg_path'):
            # WebM has no Mutagen writer. Remux native Opus without a lossy
            # encode; never advertise fabricated FLAC from this source.
            args = [tools['ffmpeg_path'], '-nostdin', '-y', '-i', path, '-map', '0:a:0', '-c:a', 'copy']
            for key in ('title', 'artist', 'album', 'genre', 'year', 'track_number'):
                value = track.get(key)
                if value not in (None, ''):
                    tag = {'year': 'date', 'track_number': 'track'}.get(key, key)
                    args += ['-metadata', f'{tag}={value}']
            args += ['-metadata', f"SOURCE={track.get('source', '')}:{track.get('source_id', '')}", temporary]
            run_tool(args, context.checkpoint)
            work, metadata_written = temporary, True
        context.checkpoint()
        # The queue may supply a deferred artwork result. Resolve only after
        # conversion/remux so optional network IO never serializes that work.
        if callable(cover):
            cover = cover()
        context.checkpoint()
        if metadata_written and cover:
            warnings.append('WebM сохранён с тегами; обложка остаётся в библиотеке. Для встроенной обложки выберите M4A или Opus.')
        if policy.embed_metadata and not metadata_written:
            warning = embed_tags(work, track, cover if policy.embed_cover else None)
            if warning:
                warnings.append(warning)
        context.checkpoint()
        from utils.audio_validation import audio_duration
        if audio_duration(work) <= 0:
            raise ValueError('Обработанный аудиофайл повреждён')
        destination = os.path.join(directory, safe_filename(track, track.get('id', context.stem)) + '.' + ext)
        # Only the queue's own identity can replace this path. No title-only
        # collision, no replacing a user-picked existing local library file.
        if os.path.exists(destination) and os.path.realpath(destination) != os.path.realpath(path):
            destination = os.path.join(directory, safe_filename(track, context.stem) + '.' + ext)
        os.replace(work, destination)
        published = True
        if work != path:
            try:
                os.remove(path)
            except OSError:
                pass
        return destination, warnings
    finally:
        if not published and os.path.basename(path).startswith(context.stem) and os.path.isfile(path):
            os.remove(path)
        if os.path.isfile(temporary):
            os.remove(temporary)


def _is_opus(path):
    try:
        with open(path, 'rb') as audio:
            header = audio.read(65536)
        return b'OpusHead' in header or b'A_OPUS' in header
    except OSError:
        return False
