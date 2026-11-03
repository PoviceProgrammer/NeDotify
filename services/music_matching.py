"""Conservative metadata comparison shared by catalogues and lyrics."""
import re
import unicodedata
from difflib import SequenceMatcher

from services.artist_identity import canonical_artist, artist_aliases

VERSION_PATTERNS = {
    'instrumental': r'\b(?:instrumental|инструментал\w*|минус|без\s+слов)\b',
    'cover': r'\b(?:cover|кавер\w*)\b',
    'live': r'\b(?:live|концерт\w*)\b',
    'acoustic': r'\b(?:acoustic|акустич\w*)\b',
    'sped': r'\b(?:sped\s*up|speed\s*up|speedup|nightcore|ускоренн\w*|ускорено)\b',
    'slowed': r'\b(?:slowed(?:\s*\+\s*reverb)?|замедленн\w*|замедлено)\b',
    'remix': r'\b(?:remix|rmx|bootleg|rework|ремикс\w*|radio\s*edit|extended\s*(?:mix|edit)|club\s*mix)\b',
}
BASE_FALLBACK_VERSIONS = {'sped', 'slowed', 'remix', 'live', 'acoustic', 'cover'}
_PRESENTATION = r'(?:official(?:\s+music)?\s+(?:video|audio)|lyrics?|lyric\s+video|visuali[sz]er|клип|премьера|hd|hq|4k)'


def normalize(value):
    text = unicodedata.normalize('NFKC', str(value or '')).casefold().replace('ё', 'е')
    text = re.sub(r"[’'`´]", '', text)
    return ' '.join(re.sub(r'[^\w]+', ' ', text, flags=re.UNICODE).split())


def similarity(want, got):
    a, b = normalize(want), normalize(got)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    # SequenceMatcher's tie breaking is directional; sorting makes identity
    # decisions stable regardless of which provider supplied either operand.
    a, b = sorted((a, b))
    # Very short titles only match on full equality: word containment would
    # give "Ты" vs "Ты и я" or "Hey" vs "Hey Ya" a perfect score and accept
    # another song's lyrics/recording (BUG-L2-004).
    if min(len(a.replace(' ', '')), len(b.replace(' ', ''))) <= 4:
        return 0.0
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


def credits(value):
    placeholders = {'?', 'unknown', 'unknown artist', 'неизвестный исполнитель', 'неизвестный артист'}
    split_pattern = r'\s*(?:,|&|\band\b|\bи\b|\bfeaturing\b|\bfeat\.?|\bft\.?|\bx\b)\s*'
    if isinstance(value, list):
        names = [str(p.get('name') or p.get('artistName') or '') if isinstance(p, dict) else str(p)
                 for p in value if p]
        result = []
        for name in names:
            for p in re.split(split_pattern, name, flags=re.I):
                s = p.strip()
                if s and s.casefold() not in placeholders:
                    result.append(s)
        return result
    return [p.strip() for p in re.split(split_pattern,
                                      str(value or ''), flags=re.I) if p.strip() and p.strip().casefold() not in placeholders]


def artist_matches(wanted, offered, settings=None):
    aliases = artist_aliases(settings)
    # Compare intact credits first: commas and ampersands can belong to a
    # band's actual name (Earth, Wind & Fire), including in structured lists.
    def names(value):
        if isinstance(value, list):
            return [str(v.get('name') or v.get('artistName') or '') if isinstance(v, dict) else str(v) for v in value]
        return [str(value or '')]
    intact_a = {canonical_artist(p, aliases) for p in names(wanted) if normalize(p)}
    intact_b = {canonical_artist(p, aliases) for p in names(offered) if normalize(p)}
    norm_a = {normalize(p) for p in intact_a if normalize(p)}
    norm_b = {normalize(p) for p in intact_b if normalize(p)}
    if norm_a and norm_a == norm_b:
        return True
    if intact_a and intact_a == intact_b:
        return True
    # Never turn a structured single-band credit into a coincidental component
    # match; only split explicit collaboration strings on both sides.
    a = {canonical_artist(p, aliases) for name in names(wanted) for p in credits(name)}
    b = {canonical_artist(p, aliases) for name in names(offered) for p in credits(name)}
    # Symmetric multi-credit rule (BUG-S4-010): a recording credited to more
    # than one artist is identified by its full credit set on BOTH sides, so a
    # solo artist never auto-matches a duo ("Miyagi" vs "Miyagi & Andy Panda").
    if len(a) > 1 or len(b) > 1:
        return bool(a and a == b)
    return bool(a and b and a.intersection(b))


def title_metadata(title, artist=''):
    """Keep the version for the first query, and retain featured credits."""
    original = str(title or '').strip()
    people = credits(artist)
    features = []
    def feature(match):
        features.extend(credits(match.group(1)))
        return ''
    clean = re.sub(r'[\[(](?:feat\.?|ft\.?|featuring)\s+([^\])]+)[\])]', feature, original, flags=re.I)
    trailing_feature = re.search(r'\s+(?:feat\.?|ft\.?|featuring)\s+(.+)$', clean, re.I)
    if trailing_feature:
        features.extend(credits(trailing_feature.group(1)))
        clean = clean[:trailing_feature.start()]
    clean = re.sub(r'[\[(]\s*' + _PRESENTATION + r'\s*[\])]', '', clean, flags=re.I)
    clean = re.sub(r'[\[(](?:prod\.?|produced)\s+by\s+[^\])]+[\])]', '', clean, flags=re.I)
    embedded = None
    parts = re.split(r'\s+[—–-]\s+', clean, maxsplit=1)
    if len(parts) == 2 and parts[0] and parts[1]:
        if not people or artist_matches(parts[0], people):
            people = credits(parts[0]) + features
            clean = parts[1]
        elif not any(re.fullmatch(pattern, parts[1].strip(), re.I) for pattern in VERSION_PATTERNS.values()):
            embedded = (parts[0].strip(), parts[1].strip())
    people.extend(features)
    version = ''
    qualifiers = re.findall(r'[\[(]([^\])]+)[\])]', clean)
    tail = re.split(r'\s+[—–-]\s+', clean)
    if len(tail) > 1:
        qualifiers.append(tail[-1])
    for kind, pattern in VERSION_PATTERNS.items():
        if any(re.search(pattern, q, re.I) for q in qualifiers):
            version = kind
            break
    def remove_variant(match):
        return '' if any(re.search(p, match.group(1), re.I) for p in VERSION_PATTERNS.values()) else match.group(0)
    base = re.sub(r'[\[(]([^\])]+)[\])]', remove_variant, clean)
    if len(tail) > 1 and any(re.search(p, tail[-1], re.I) for p in VERSION_PATTERNS.values()):
        base = ' - '.join(tail[:-1])
    if not version:
        for kind, pattern in VERSION_PATTERNS.items():
            suffix = re.search(r'\s+(' + pattern + r')\s*$', base, re.I)
            if suffix:
                cand = base[:suffix.start()].rstrip(' -–—')
                if cand.strip():
                    version = kind
                    base = cand
                    break
    return {'title': ' '.join(clean.split()).strip(), 'base_title': ' '.join(base.split()).strip(),
            'artists': list(dict.fromkeys(p for p in people if p)), 'version': version, 'embedded': embedded,
            'reverse_credit': (parts[1].strip(), parts[0].strip()) if trailing_feature and embedded else None}
