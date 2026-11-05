"""Local query suggestions without a provider request or persistent vocabulary."""

import re


_LATIN_KEYS = "`qwertyuiop[]asdfghjkl;'zxcvbnm,."
_RUSSIAN_KEYS = "ёйцукенгшщзхъфывапролджэячсмитьбю"
_TO_RUSSIAN = str.maketrans(_LATIN_KEYS + _LATIN_KEYS.upper(), _RUSSIAN_KEYS + _RUSSIAN_KEYS.upper())
_TO_LATIN = str.maketrans(_RUSSIAN_KEYS + _RUSSIAN_KEYS.upper(), _LATIN_KEYS + _LATIN_KEYS.upper())
_WORDS = re.compile(r"[^\W\d_]+", re.UNICODE)


def _distance(left, right, ceiling):
    if abs(len(left) - len(right)) > ceiling:
        return ceiling + 1
    previous = list(range(len(right) + 1))
    before_previous = previous
    for left_index, left_letter in enumerate(left, 1):
        current = [left_index]
        for right_index, right_letter in enumerate(right, 1):
            value = min(current[-1] + 1, previous[right_index] + 1, previous[right_index - 1] + (left_letter != right_letter))
            if left_index > 1 and right_index > 1 and left_letter == right[right_index - 2] and left[left_index - 2] == right_letter:
                value = min(value, before_previous[right_index - 2] + 1)
            current.append(value)
        if min(current) > ceiling:
            return ceiling + 1
        before_previous, previous = previous, current
    return previous[-1]


def convert_layout(query: str) -> str:
    """Convert a query string between Russian and Latin keyboard layouts.
    If the string contains Latin characters and no Cyrillic, converts to Russian layout.
    If the string contains Cyrillic characters and no Latin, converts to Latin layout.
    Returns the converted string if different from original, or empty string.
    """
    if not isinstance(query, str) or not query.strip():
        return ""
    text = query.strip()
    has_latin = bool(re.search(r"[a-z]", text, re.I))
    has_cyrillic = bool(re.search(r"[а-яё]", text, re.I))
    if has_latin and not has_cyrillic:
        converted = text.translate(_TO_RUSSIAN)
    elif has_cyrillic and not has_latin:
        converted = text.translate(_TO_LATIN)
    else:
        return ""
    return converted if converted.casefold() != text.casefold() else ""


def suggest_search_queries(db, query, limit=3):
    if not isinstance(query, str) or not 3 <= len(query.strip()) <= 120:
        return []
    if type(limit) is not int:
        return []
    limit = min(3, max(0, limit))
    if not limit:
        return []
    query = query.strip()
    normalized = query.casefold().replace("ё", "е")
    letters = _WORDS.findall(query)
    if not letters or sum(map(len, letters)) < 3:
        return []
    suggestions = []
    seen = {normalized}

    def add(candidate, reason):
        key = candidate.casefold().replace("ё", "е")
        if key not in seen and len(suggestions) < limit:
            seen.add(key)
            suggestions.append({"query": candidate, "reason": reason})

    layout = convert_layout(query) or None
    if layout:
        add(layout, "layout")
    rows = db.conn.execute(
        "SELECT title, artist, album FROM tracks ORDER BY added_at DESC, id DESC LIMIT 600"
    ).fetchall()
    candidates = {}
    for row in rows:
        for field in ("title", "artist", "album"):
            value = row[field]
            if not isinstance(value, str):
                continue
            value = value[:240]
            for candidate in [value, *_WORDS.findall(value)[:16]]:
                candidate = candidate.strip()
                if not 3 <= len(candidate) <= 120:
                    continue
                key = candidate.casefold().replace("ё", "е")
                if key not in candidates:
                    candidates[key] = candidate
                if len(candidates) >= 4000:
                    break
            if len(candidates) >= 4000:
                break
        if len(candidates) >= 4000:
            break
    if normalized in candidates:
        return []
    matches = []
    variants = [(normalized, "typo")]
    if layout:
        variants.append((layout.casefold().replace("ё", "е"), "layout"))
    for variant, reason in variants:
        threshold = 1 if len(variant) < 7 else 2
        for candidate, display in candidates.items():
            if abs(len(candidate) - len(variant)) > threshold:
                continue
            distance = _distance(variant, candidate, threshold)
            if 0 <= distance <= threshold:
                matches.append((distance, abs(len(candidate) - len(variant)), candidate, display, reason))
    for _, _, _, display, reason in sorted(matches):
        add(display, reason)
    return suggestions
