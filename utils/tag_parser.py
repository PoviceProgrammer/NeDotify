"""
NeDotify - Tag Parser
Parses audio file metadata (ID3, FLAC, WAV) using mutagen.
"""

import os
import io
import hashlib
import logging
import struct
from typing import Optional
logger = logging.getLogger(__name__)

try:
    from mutagen import File as MutagenFile
    from mutagen.id3 import ID3, TIT2, TPE1, TALB, TCON, TYER, TDRC, APIC, ID3NoHeaderError
    from mutagen.mp3 import MP3
    from mutagen.flac import FLAC, Picture
    from mutagen.oggvorbis import OggVorbis
    from mutagen.mp4 import MP4, MP4Cover
    HAS_MUTAGEN = True
except ImportError:
    HAS_MUTAGEN = False


SUPPORTED_FORMATS = {'.mp3', '.flac', '.wav', '.ogg', '.m4a', '.wma', '.aac'}


def is_audio_file(filepath: str) -> bool:
    """Check if a file is a supported audio format."""
    _, ext = os.path.splitext(filepath.lower())
    return ext in SUPPORTED_FORMATS


def parse_tags(filepath: str) -> dict:
    """
    Parse audio file tags and return metadata dict.
    Returns: {title, artist, album, duration, bitrate, sample_rate, format,
              file_size, genre, year, track_number, cover_data, cover_mime}
    """
    result = {
        "title": os.path.splitext(os.path.basename(filepath))[0],
        "artist": "Unknown Artist",
        "album": "Unknown Album",
        "duration": 0.0,
        "bitrate": 0,
        "sample_rate": 0,
        "format": os.path.splitext(filepath)[1].lstrip('.').upper(),
        "file_size": 0,
        "genre": None,
        "year": None,
        "track_number": None,
        "cover_data": None,
        "cover_mime": None,
    }

    try:
        result["file_size"] = os.path.getsize(filepath)
    except OSError:
        pass

    if HAS_MUTAGEN:
        try:
            audio = MutagenFile(filepath, easy=True)
            if audio:
                if hasattr(audio, 'info') and audio.info:
                    result["duration"] = getattr(audio.info, 'length', 0.0)
                    result["bitrate"] = getattr(audio.info, 'bitrate', 0)
                    result["sample_rate"] = getattr(audio.info, 'sample_rate', 0)

                result["title"] = _get_tag(audio, 'title', result["title"])
                result["artist"] = _get_tag(audio, 'artist', result["artist"])
                result["album"] = _get_tag(audio, 'album', result["album"])
                result["genre"] = _get_tag(audio, 'genre')

                date = _get_tag(audio, 'date')
                if date:
                    try:
                        result["year"] = int(str(date)[:4])
                    except (ValueError, IndexError):
                        pass

                track_num = _get_tag(audio, 'tracknumber')
                if track_num:
                    try:
                        result["track_number"] = int(str(track_num).split('/')[0])
                    except (ValueError, IndexError):
                        pass

            result["cover_data"], result["cover_mime"] = _extract_cover(filepath)
        except Exception as e:
            logger.warning("Could not parse audio tags: %s", e)

    # Metadata Cleanup / Normalization
    import re
    junk_patterns = [
        r"(?i)\(official.*?video\)", r"(?i)\[official.*?video\]",
        r"(?i)\(official.*?audio\)", r"(?i)\[official.*?audio\]",
        r"(?i)\(lyric.*?video\)", r"(?i)\[lyric.*?video\]",
        r"(?i)\(music.*?video\)", r"(?i)\[music.*?video\]",
        r"(?i)128kbps", r"(?i)320kbps", r"(?i)\(audio\)", r"(?i)\[audio\]",
        r"(?i)\(visualizer\)", r"(?i)\[visualizer\]",
        r"(?i)\bHD\b", r"(?i)\bHQ\b", r"(?i)\(lyrics?\)", r"(?i)\[lyrics?\]"
    ]
    
    for pattern in junk_patterns:
        result["title"] = re.sub(pattern, "", result["title"]).strip()
        if result["artist"]:
            result["artist"] = re.sub(pattern, "", result["artist"]).strip()
            
    # Remove extra spaces/dashes that might be left behind
    result["title"] = re.sub(r"\s+", " ", result["title"]).strip(" -_~")
    
    if not result["artist"] or result["artist"] == "Unknown Artist":
        # Fallback to parsing from title if there's a dash and no artist
        if " - " in result["title"]:
            parts = result["title"].rsplit(" - ", 1)
            if not parts[0].strip().isdigit():
                result["artist"] = parts[0].strip()
            result["title"] = parts[1].strip()

    return result


def find_sidecar_lrc_file(filepath: str):
    """Look for sidecar .lrc or .synced.lrc in the same directory as audio file."""
    if not filepath or not os.path.isfile(filepath):
        return None
    try:
        base, _ = os.path.splitext(filepath)
        for ext in ('.lrc', '.synced.lrc', '.LRC'):
            candidate = base + ext
            if os.path.isfile(candidate):
                with open(candidate, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read().strip()
                if content:
                    return content
    except Exception:
        pass
    return None


def extract_embedded_lyrics(filepath: str) -> str:
    """Return lyrics from sidecar file, ID3 SYLT/USLT, Vorbis LYRICS, or MP4 ©lyr."""
    sidecar = find_sidecar_lrc_file(filepath)
    if sidecar:
        return sidecar
    if not HAS_MUTAGEN:
        return ""
    try:
        ext = os.path.splitext(filepath)[1].lower()
        audio = MutagenFile(filepath)
        if audio is None or audio.tags is None:
            return ""
        texts = []
        if ext == '.mp3':
            for key in audio.tags:
                if key.startswith('SYLT'):
                    sylt = audio.tags[key]
                    if hasattr(sylt, 'text') and sylt.text:
                        lrc_lines = []
                        for item in sylt.text:
                            if isinstance(item, (list, tuple)) and len(item) >= 2:
                                line_text, t = str(item[0] or ''), item[1]
                                try:
                                    t_ms = int(t)
                                    m = t_ms // 60000
                                    s = (t_ms % 60000) // 1000
                                    cs = (t_ms % 1000) // 10
                                    lrc_lines.append(f"[{m:02d}:{s:02d}.{cs:02d}]{line_text}")
                                except (ValueError, TypeError):
                                    pass
                        if lrc_lines:
                            return "\n".join(lrc_lines)
            for key in audio.tags:
                if key.startswith('USLT'):
                    texts.append(audio.tags[key].text)
        elif ext in ('.m4a', '.mp4', '.aac'):
            texts.append(audio.tags.get('\xa9lyr', []))
        else:
            for key in ('LYRICS', 'UNSYNCEDLYRICS', 'lyrics', 'unsyncedlyrics'):
                texts.append(audio.tags.get(key, []))
        def normalize(value):
            if isinstance(value, (list, tuple)):
                return '\n'.join(normalize(item) for item in value)
            if isinstance(value, bytes):
                return value.decode('utf-8', errors='replace')
            return str(value or '')
        return "\n".join(normalize(t).strip() for t in texts if normalize(t).strip())
    except Exception:
        return ""


def _get_tag(audio, key: str, default=None):
    """Safely get a tag value."""
    try:
        val = audio.get(key)
        if not val:
            # Mutagen's easy view does not translate ID3 frames embedded in
            # WAV containers into easy keys, even though write_tags stores
            # those frames there. Read the canonical frame as a fallback.
            frame_keys = {
                'title': ('TIT2',), 'artist': ('TPE1',), 'album': ('TALB',),
                'genre': ('TCON',), 'date': ('TDRC', 'TYER'),
                'tracknumber': ('TRCK',),
            }.get(key, ())
            tags = getattr(audio, 'tags', None)
            for frame_key in frame_keys:
                frame = tags.get(frame_key) if tags is not None else None
                if frame is not None:
                    val = getattr(frame, 'text', frame)
                    if val:
                        break
        if val:
            return str(val[0]) if isinstance(val, list) else str(val)
    except (KeyError, IndexError, TypeError):
        pass
    return default


def _extract_cover(filepath: str) -> tuple:
    """Extract cover art bytes and MIME type from audio file."""
    try:
        ext = os.path.splitext(filepath)[1].lower()

        if ext == '.mp3':
            try:
                tags = ID3(filepath)
                pictures = sorted(tags.getall('APIC'), key=lambda item: item.type != 3)
                for apic in pictures:
                    mime = cover_mime_from_bytes(apic.data)
                    if mime:
                        return apic.data, mime
            except Exception:
                pass

        elif ext == '.flac':
            try:
                flac = FLAC(filepath)
                if flac.pictures:
                    pic = sorted(flac.pictures, key=lambda item: item.type != 3)[0]
                    return pic.data, cover_mime_from_bytes(pic.data)
            except Exception:
                pass

        elif ext == '.ogg':
            try:
                ogg = OggVorbis(filepath)
                # OGG stores pictures in metadata_block_picture
                import base64
                if 'metadata_block_picture' in ogg:
                    pictures = [Picture(base64.b64decode(value)) for value in ogg['metadata_block_picture']]
                    pic = sorted(pictures, key=lambda item: item.type != 3)[0]
                    return pic.data, cover_mime_from_bytes(pic.data)
            except Exception:
                pass

        # For other formats, try generic mutagen approach
        audio = MutagenFile(filepath)
        if audio and hasattr(audio, 'tags') and audio.tags:
            # M4A/AAC
            for key in ('covr', 'APIC:', 'APIC'):
                if key in audio.tags:
                    cover = audio.tags[key]
                    if isinstance(cover, list) and cover:
                        c_item = cover[0]
                        mime = 'image/png' if getattr(c_item, 'imageformat', None) == 14 else 'image/jpeg'
                        return bytes(c_item), mime
                    elif hasattr(cover, 'data'):
                        return bytes(cover.data), getattr(cover, 'mime', 'image/jpeg')

    except Exception:
        pass

    return None, None


def cover_mime_from_bytes(data):
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if data.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if data.startswith((b'GIF87a', b'GIF89a')):
        return 'image/gif'
    if data.startswith(b'RIFF') and data[8:12] == b'WEBP':
        return 'image/webp'
    return None


def save_cover_to_file(cover_data: bytes, cover_mime: str,
                       output_dir: str, track_id: int) -> Optional[str]:
    """Atomically publish artwork using the shared cover_<database id> name."""
    import tempfile

    if not isinstance(cover_data, bytes) or not cover_data:
        return None
    temporary = None
    try:
        identifier = int(track_id)
        if identifier <= 0:
            return None
        mime = cover_mime_from_bytes(cover_data) or str(cover_mime or '').lower().split(';', 1)[0].strip()
        ext = {'image/jpeg': '.jpg', 'image/jpg': '.jpg', 'image/png': '.png',
               'image/webp': '.webp', 'image/gif': '.gif'}.get(mime)
        if ext is None:
            return None
        os.makedirs(output_dir, exist_ok=True)
        filepath = os.path.join(output_dir, f'cover_{identifier}{ext}')
        with tempfile.NamedTemporaryFile(mode='wb', dir=output_dir, prefix='.cover-', suffix=ext,
                                         delete=False) as f:
            temporary = f.name
            f.write(cover_data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, filepath)
        return filepath
    except (OSError, TypeError, ValueError, OverflowError):
        return None
    finally:
        if temporary and os.path.exists(temporary):
            try:
                os.remove(temporary)
            except OSError:
                logger.debug('Could not remove temporary cover', exc_info=True)


def write_tags(
    filepath: str,
    title: Optional[str] = None,
    artist: Optional[str] = None,
    album: Optional[str] = None,
    genre: Optional[str] = None,
    year: Optional[int] = None,
    cover_bytes: Optional[bytes] = None,
    cover_mime: str = "image/jpeg",
    clear_year: bool = False,
) -> bool:
    """
    Safely write physical ID3v2/Vorbis/MP4 tags to an audio file using mutagen.
    Checks write permissions, embeds cover art, and writes atomically.
    """
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Аудиофайл не найден: {filepath}")

    if not os.access(filepath, os.W_OK):
        raise PermissionError(f"Файл доступен только для чтения: {filepath}")

    if not HAS_MUTAGEN:
        raise RuntimeError("Модуль mutagen не установлен")

    import shutil
    import tempfile
    import base64

    # The original stays intact until the replacement is fully saved and
    # fsynced. The sibling copy guarantees an atomic same-volume replace.
    original_path = os.path.abspath(filepath)
    backup_fd, backup_path = tempfile.mkstemp(prefix="aura_tag_backup_", suffix=os.path.splitext(filepath)[1], dir=os.path.dirname(original_path))
    os.close(backup_fd)
    shutil.copy2(filepath, backup_path)
    filepath = backup_path

    try:
        _, ext = os.path.splitext(filepath.lower())

        if ext in ('.mp3', '.aac', '.wav'):
            wave_audio = None
            if ext == '.wav':
                from mutagen.wave import WAVE
                wave_audio = WAVE(filepath)
                if wave_audio.tags is None:
                    wave_audio.add_tags()
            try:
                tags = wave_audio.tags if wave_audio is not None else ID3(filepath)
            except ID3NoHeaderError:
                tags = ID3()

            if title is not None:
                tags.setall('TIT2', [TIT2(encoding=3, text=str(title))])
            if artist is not None:
                tags.setall('TPE1', [TPE1(encoding=3, text=str(artist))])
            if album is not None:
                tags.setall('TALB', [TALB(encoding=3, text=str(album))])
            if genre is not None:
                tags.setall('TCON', [TCON(encoding=3, text=str(genre))])
            if year is not None and str(year).strip():
                tags.setall('TDRC', [TDRC(encoding=3, text=str(year))])
                tags.setall('TYER', [TYER(encoding=3, text=str(year))])
            if clear_year:
                tags.delall('TDRC')
                tags.delall('TYER')

            if cover_bytes:
                tags.setall(
                    'APIC',
                    [APIC(
                        encoding=3,
                        mime=cover_mime or 'image/jpeg',
                        type=3,  # 3 is cover front
                        desc='Cover',
                        data=cover_bytes
                    )]
                )

            if wave_audio is not None:
                wave_audio.save()
            else:
                tags.save(filepath, v2_version=3)

        elif ext == '.flac':
            audio = FLAC(filepath)
            if title is not None:
                audio['title'] = [str(title)]
            if artist is not None:
                audio['artist'] = [str(artist)]
            if album is not None:
                audio['album'] = [str(album)]
            if genre is not None:
                audio['genre'] = [str(genre)]
            if year is not None and str(year).strip():
                audio['date'] = [str(year)]
            if clear_year:
                audio.pop('date', None)
                audio.pop('year', None)

            if cover_bytes:
                pic = Picture()
                pic.type = 3
                pic.mime = cover_mime or 'image/jpeg'
                pic.desc = 'Cover'
                pic.data = cover_bytes
                audio.clear_pictures()
                audio.add_picture(pic)

            audio.save()

        elif ext in ('.m4a', '.mp4'):
            audio = MP4(filepath)
            if title is not None:
                audio['\xa9nam'] = [str(title)]
            if artist is not None:
                audio['\xa9ART'] = [str(artist)]
            if album is not None:
                audio['\xa9alb'] = [str(album)]
            if genre is not None:
                audio['\xa9gen'] = [str(genre)]
            if year is not None and str(year).strip():
                audio['\xa9day'] = [str(year)]
            if clear_year:
                audio.pop('\xa9day', None)

            if cover_bytes:
                fmt = MP4Cover.FORMAT_JPEG
                if cover_mime and 'png' in cover_mime.lower():
                    fmt = MP4Cover.FORMAT_PNG
                audio['covr'] = [MP4Cover(cover_bytes, imageformat=fmt)]

            audio.save()

        elif ext == '.ogg':
            audio = OggVorbis(filepath)
            if title is not None:
                audio['title'] = [str(title)]
            if artist is not None:
                audio['artist'] = [str(artist)]
            if album is not None:
                audio['album'] = [str(album)]
            if genre is not None:
                audio['genre'] = [str(genre)]
            if year is not None and str(year).strip():
                audio['date'] = [str(year)]
            if clear_year:
                audio.pop('date', None)
                audio.pop('year', None)

            if cover_bytes:
                pic = Picture()
                pic.type = 3
                pic.mime = cover_mime or 'image/jpeg'
                pic.desc = 'Cover'
                pic.data = cover_bytes
                audio['metadata_block_picture'] = [base64.b64encode(pic.write()).decode('ascii')]

            audio.save()

        elif ext == '.wma':
            from mutagen.asf import ASF, ASFByteArrayAttribute
            audio = ASF(filepath)
            for key, value in [('Title', title), ('Author', artist), ('WM/AlbumTitle', album), ('WM/Genre', genre), ('WM/Year', year)]:
                if value is not None:
                    audio[key] = [str(value)]
            if clear_year:
                audio.pop('WM/Year', None)
            if cover_bytes:
                picture = struct.pack('<BI', 3, len(cover_bytes)) + (cover_mime + '\0Cover\0').encode('utf-16-le') + cover_bytes
                audio['WM/Picture'] = [ASFByteArrayAttribute(picture)]
            audio.save()
        else:
            # Fallback for other formats with EasyID3/EasyMutagen
            audio = MutagenFile(filepath, easy=True)
            if audio is not None:
                if title is not None:
                    audio['title'] = [str(title)]
                if artist is not None:
                    audio['artist'] = [str(artist)]
                if album is not None:
                    audio['album'] = [str(album)]
                if genre is not None:
                    audio['genre'] = [str(genre)]
                if year is not None and str(year).strip():
                    audio['date'] = [str(year)]
                if clear_year:
                    audio.pop('date', None)
                    audio.pop('year', None)
                audio.save()

        # Windows requires a writable handle for _commit/fsync. The temp file
        # is private to this operation, so rb+ safely flushes the mutagen output
        # before the atomic replace.
        with open(backup_path, 'rb+') as saved:
            os.fsync(saved.fileno())
        os.replace(backup_path, original_path)
        return True

    except Exception as e:
        # Atomic rollback on any mutagen write failure
        if os.path.exists(backup_path):
            os.remove(backup_path)
        raise RuntimeError(f"Ошибка при записи тегов в файл: {e}")

