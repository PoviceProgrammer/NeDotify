"""
NeDotify - Tag Parser
Parses audio file metadata (ID3, FLAC, WAV) using mutagen.
"""

import os
import io
import hashlib
from typing import Optional

try:
    from mutagen import File as MutagenFile
    from mutagen.id3 import ID3
    from mutagen.mp3 import MP3
    from mutagen.flac import FLAC
    from mutagen.oggvorbis import OggVorbis
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
            print(f"[TagParser] Error parsing {filepath}: {e}")

    # Metadata Cleanup / Normalization
    import re
    junk_patterns = [
        r"(?i)\(official.*?video\)", r"(?i)\[official.*?video\]",
        r"(?i)\(official.*?audio\)", r"(?i)\[official.*?audio\]",
        r"(?i)\(lyric.*?video\)", r"(?i)\[lyric.*?video\]",
        r"(?i)\(music.*?video\)", r"(?i)\[music.*?video\]",
        r"(?i)128kbps", r"(?i)320kbps", r"(?i)\(audio\)", r"(?i)\[audio\]",
        r"(?i)\(visualizer\)", r"(?i)\[visualizer\]",
        r"(?i)HD", r"(?i)HQ", r"(?i)\(lyrics?\)", r"(?i)\[lyrics?\]"
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
            parts = result["title"].split(" - ", 1)
            result["artist"] = parts[0].strip()
            result["title"] = parts[1].strip()

    return result


def _get_tag(audio, key: str, default=None):
    """Safely get a tag value."""
    try:
        val = audio.get(key)
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
                for key in tags:
                    if key.startswith('APIC'):
                        apic = tags[key]
                        return apic.data, apic.mime
            except Exception:
                pass

        elif ext == '.flac':
            try:
                flac = FLAC(filepath)
                if flac.pictures:
                    pic = flac.pictures[0]
                    return pic.data, pic.mime
            except Exception:
                pass

        elif ext == '.ogg':
            try:
                ogg = OggVorbis(filepath)
                # OGG stores pictures in metadata_block_picture
                import base64
                if 'metadata_block_picture' in ogg:
                    data = base64.b64decode(ogg['metadata_block_picture'][0])
                    return data, 'image/png'
            except Exception:
                pass

        # For other formats, try generic mutagen approach
        audio = MutagenFile(filepath)
        if audio and hasattr(audio, 'tags') and audio.tags:
            # M4A/AAC
            if hasattr(audio.tags, '_DictProxy__dict'):
                for key in ('covr', 'APIC:'):
                    if key in audio.tags:
                        cover = audio.tags[key]
                        if isinstance(cover, list) and cover:
                            return bytes(cover[0]), 'image/jpeg'

    except Exception:
        pass

    return None, None


def save_cover_to_file(cover_data: bytes, cover_mime: str,
                       output_dir: str, track_id: int) -> Optional[str]:
    """Save cover art to a file. Returns the file path."""
    if not cover_data:
        return None

    os.makedirs(output_dir, exist_ok=True)

    ext = '.jpg'
    if cover_mime:
        if 'png' in cover_mime:
            ext = '.png'
        elif 'webp' in cover_mime:
            ext = '.webp'

    filename = f"cover_{track_id}{ext}"
    filepath = os.path.join(output_dir, filename)

    try:
        with open(filepath, 'wb') as f:
            f.write(cover_data)
        return filepath
    except IOError:
        return None
