"""Upload cleanup scoped to lyrics, without relaxing catalogue recording identity."""
import os
import re

from services.artist_identity import artist_aliases, canonical_artist
from services.music_matching import BASE_FALLBACK_VERSIONS, VERSION_PATTERNS, normalize, title_metadata

_VIDEO = r'(?:official(?:\s+music)?\s+video|(?:официальный\s+)?(?:видео)?клип|официальное\s+видео)'
_PRESENTATION = _VIDEO + r'(?:\s+(?:4k|hd|hq))?'
_EDITIONS = (
    r'(?:'
    r'(?:\d{4}\s+)?remaster(?:ed)?(?:\s+\d{4})?'
    r'|digital\s+remaster'
    r'|deluxe(?:\s+(?:edition|version))?'
    r'|(?:original\s+(?:game\s+)?)?soundtrack'
    r'|ost'
    r'|anniversary(?:\s+edition)?'
    r'|special\s+edition'
    r'|expanded\s+edition'
    r')'
)


def lyrics_metadata(title, artist=''):
    text = str(title or '').strip()
    video_suffix = re.search(r'\s+(?:[-–—|]\s*)?' + _PRESENTATION + r'\s*$', text, re.I)
    video = bool(video_suffix or re.search(r'[\[(]\s*' + _PRESENTATION + r'\s*[\])]', text, re.I))
    if video_suffix:
        text = text[:video_suffix.start()].strip()
    text = re.sub(r'[\[(]\s*' + _PRESENTATION + r'\s*[\])]', '', text, flags=re.I).strip()
    text = re.sub(r'\s+[-–—|]\s*' + _EDITIONS + r'\s*$', '', text, flags=re.I).strip()
    text = re.sub(r'[\[(]\s*' + _EDITIONS + r'\s*[\])]', '', text, flags=re.I).strip()
    # Uploaders often omit brackets. Only explicit speed/remix suffixes take
    # this recovery path; live/cover/instrumental still require their own text.
    if not title_metadata(text, artist)['version']:
        for kind, pattern in VERSION_PATTERNS.items():
            if kind not in BASE_FALLBACK_VERSIONS:
                continue
            suffix = re.search(r'\s+(' + pattern + r')\s*$', text, re.I)
            if suffix:
                text = text[:suffix.start()].rstrip(' -–—') + ' (' + suffix.group(1) + ')'
                break
    result = title_metadata(text, artist)
    result['video'] = video
    return result


def native_lyrics_name(value):
    """Genius appends a Latin translation to native Cyrillic catalogue names."""
    value = str(value or '').strip()
    if title_metadata(value)['version']:
        return value
    match = re.fullmatch(r'(.*[А-Яа-яЁё].*?)\s*\(([A-Za-z][^()]*)\)', value)
    return match[1].strip() if match and not re.search(r'[А-Яа-яЁё]', match[2]) else value


def lyrics_override_keys(title, artist, file_path, source, source_id, settings):
    """Preferred identity followed by older identities that remain readable."""
    keys = []
    if source in ('youtube', 'soundcloud') and source_id:
        keys.append(f'{source}:{source_id}')
    if file_path and not str(file_path).lstrip().casefold().startswith(('http://', 'https://')):
        keys.append(f'local:{os.path.normcase(os.path.abspath(file_path))}')
    metadata = lyrics_metadata(title, artist)
    aliases = artist_aliases(settings)
    artists = ','.join(canonical_artist(name, aliases) for name in metadata['artists'])
    keys.append(f"meta:{normalize(metadata['title'])}\0{artists}\0{metadata['version']}")
    keys.append(f"meta:{str(title or '').strip().lower()}\0{str(artist or '').strip().lower()}\0")
    return tuple(dict.fromkeys(keys))
