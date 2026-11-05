"""Deterministic Cyrillic<->Latin transcription for lyrics search forms (BUG-L2-002).

The same Russian artist is indexed under both scripts by different providers
(Скриптонит/Skriptonit, Мот/Mot). The lyrics cascade searched only with the
metadata spelling, so a correct record was invisible whenever the source had
indexed the other script.

This module builds the ALTERNATE spelling of an artist name. It is a search
aid only: acceptance rules (services/music_matching.py) stay untouched and
strict -- a form found through the alternate spelling is still validated
against title similarity, version and duration, and the artist comparison
simply gains one extra deterministic pass through the Latin domain
(LyricsLookup.accept). Nothing here is a fuzzy "sounds like" matcher: the
mapping is a fixed table, and the reverse (Latin->Cyrillic) direction is only
offered when it round-trips exactly, which filters pseudo-transliterations
("Oxxxymiron"/"Оксимирон" is a different word, not a transcription, and gets
no automatic form).

GOST 7.79-2000 (system B) letter values, with two stage-name adjustments:
``ё`` maps to ``e`` (the dominant billing convention, e.g. Ёлка -> Elka) and
``х`` maps to ``kh``. Non-Cyrillic characters pass through unchanged.
"""

import re

_CYRILLIC_RE = re.compile(r'[а-яё]', re.IGNORECASE)
_ASCII_LETTERS_RE = re.compile(r'[a-z]', re.IGNORECASE)

# Cyrillic -> Latin. One letter each; ъ/ь are silent.
_CYR_TO_LAT = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e',
    'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
    'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
    'ф': 'f', 'х': 'kh', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'shch',
    'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
}

# Latin -> Cyrillic, longest digraphs first so 'shch' beats 'sh' and 'ya'
# beats 'y'. Reverse mappings are inherently ambiguous; this direction is
# gated by the round-trip check in alt_script_artist(), which keeps only
# names whose guessed Cyrillic spelling transcribes back to the original.
_LAT_DIGRAPHS = (
    ('shch', 'щ'), ('kh', 'х'), ('sh', 'ш'), ('ch', 'ч'), ('zh', 'ж'),
    ('ts', 'ц'), ('ya', 'я'), ('yu', 'ю'), ('yo', 'ё'),
)
_LAT_TO_CYR = {
    'a': 'а', 'b': 'б', 'c': 'к', 'd': 'д', 'e': 'е', 'f': 'ф', 'g': 'г',
    'h': 'х', 'i': 'и', 'j': 'й', 'k': 'к', 'l': 'л', 'm': 'м', 'n': 'н',
    'o': 'о', 'p': 'п', 'r': 'р', 's': 'с', 't': 'т', 'u': 'у', 'v': 'в',
    'w': 'в', 'x': 'кс', 'y': 'и', 'z': 'з',
}


def has_cyrillic(text):
    return bool(_CYRILLIC_RE.search(str(text or '')))


def has_ascii_letters(text):
    return bool(_ASCII_LETTERS_RE.search(str(text or '')))


def to_latin(text):
    """Transcribe Cyrillic characters to Latin; everything else unchanged."""
    source = str(text or '')
    if not has_cyrillic(source):
        return source
    return ''.join(_CYR_TO_LAT.get(ch, ch) if ch.isalpha() else ch
                   for ch in source.lower())


def to_cyrillic(text):
    """Guess the Cyrillic spelling of a Latin name (digraphs first)."""
    source = str(text or '').lower()
    if not has_ascii_letters(source):
        return source
    out, i = [], 0
    while i < len(source):
        for digraph, cyr in _LAT_DIGRAPHS:
            if source.startswith(digraph, i):
                out.append(cyr)
                i += len(digraph)
                break
        else:
            ch = source[i]
            out.append(_LAT_TO_CYR.get(ch, ch) if ch.isalpha() else ch)
            i += 1
    return ''.join(out)


def alt_script_artist(artist):
    """Return the artist name in the other script, or None when not applicable.

    Cyrillic names always get their Latin transcription (deterministic). Latin
    names get a Cyrillic guess only when that guess transcribes back to the
    original name, which rejects pseudo-transcriptions of e.g. English names
    while keeping stage names like Skriptonit/Skriptonit.
    """
    name = str(artist or '').strip()
    if not name:
        return None
    if has_cyrillic(name):
        latin = to_latin(name)
        return latin if latin != name.casefold() else None
    if not has_ascii_letters(name) or has_cyrillic(name):
        return None
    guessed = to_cyrillic(name)
    if not has_cyrillic(guessed):
        return None
    # Round-trip gate: a Latin name is only retried as Cyrillic when its
    # guessed spelling transcribes back letter-for-letter (case/punctuation
    # insensitive). This keeps "radiohead" (радиохеад -> radiohead) eligible
    # while rejecting names whose reverse guess is a different word.
    if to_latin(guessed) != re.sub(r'[^a-z]', '', name.lower()):
        return None
    return guessed
