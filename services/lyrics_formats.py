"""Bounded lyric parsers. Word timing is retained only when the source supplies it.

Times are milliseconds. Ordinary LRC and plain text each have a single text
fragment per line; this is storage convenience, never a claim of word timing.
No third-party parser or rendering implementation is embedded here.
"""
import math
import re
import xml.etree.ElementTree as ET

MAX_INPUT_BYTES = 2 * 1024 * 1024
MAX_LINES = 5000
MAX_WORDS = 50000
MAX_TIME_MS = 24 * 60 * 60 * 1000
_SYNC_TYPES = {'word', 'syllable', 'line', 'plain'}
_LRC_TIME = re.compile(r'\[(\d{1,3}):(\d{2})(?:[.:](\d+))?\]')
_WORD_TIME = re.compile(r'<(\d{1,3}):(\d{2})(?:[.:](\d+))?>')


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _duration(value):
    if not _number(value) or value < 0 or value > MAX_TIME_MS:
        raise ValueError('Invalid track duration')
    return value


def validate_lyrics(model, duration_ms=0):
    """Validate normalized data, including decoded cache/API payloads.

    Parallel vocal lines may overlap. Within a line, source order must follow
    start time; explicit short or zero-duration syllables remain valid.
    """
    try:
        duration_ms = _duration(duration_ms)
        if not isinstance(model, dict) or model.get('syncType') not in _SYNC_TYPES:
            return False
        lines = model.get('lines')
        if not isinstance(lines, list) or not lines or len(lines) > MAX_LINES:
            return False
        limit = min(MAX_TIME_MS, duration_ms + max(2000, duration_ms * .01)) if duration_ms else MAX_TIME_MS
        count, text_length, previous_line = 0, 0, -1
        for line in lines:
            if not isinstance(line, dict):
                return False
            start, end = line.get('startMs'), line.get('endMs')
            if not (_number(start) and _number(end) and 0 <= start <= end <= limit and start >= previous_line):
                return False
            previous_line = start
            words = line.get('words')
            if not isinstance(words, list) or not words:
                return False
            previous_word = start
            for word in words:
                if not isinstance(word, dict) or not isinstance(word.get('text'), str):
                    return False
                word_start, word_end = word.get('startMs'), word.get('endMs')
                if not (_number(word_start) and _number(word_end) and start <= word_start <= word_end <= end and word_start >= previous_word):
                    return False
                previous_word = word_start
                text_length += len(word['text'])
                count += 1
            if not any(word['text'].strip() for word in words):
                return False
        return count <= MAX_WORDS and text_length <= MAX_INPUT_BYTES
    except (TypeError, ValueError, OverflowError):
        return False


def _word(text, start, end):
    return {'text': text, 'startMs': round(start, 3), 'endMs': round(end, 3)}


def _line(words, start, end):
    return {'startMs': round(start, 3), 'endMs': round(end, 3), 'words': words}


def _stamp(match):
    minute, second, fraction = match.groups()
    if int(second) >= 60:
        raise ValueError('Invalid lyric seconds')
    frac_str = (fraction or '0')[:3].ljust(3, '0')
    return int(minute) * 60000 + int(second) * 1000 + int(frac_str)


def _plain(text):
    rows = text.splitlines()
    if len(rows) > MAX_LINES:
        raise ValueError('Too many lyric lines')
    return {'syncType': 'plain', 'lines': [_line([_word(line, 0, 0)], 0, 0)
            for line in rows if line.strip()]}


def _lrc(text, duration_ms):
    offset_tags = re.findall(r'\[offset:\s*([+-]?\d+)\s*\]', text, re.I)
    offset = int(offset_tags[-1]) if offset_tags else 0
    if abs(offset) > MAX_TIME_MS:
        raise ValueError('Invalid LRC offset')
    rows = []
    for raw in text.splitlines():
        matches = list(_LRC_TIME.finditer(raw))
        if not matches:
            continue
        # Leading repeated stamps represent repeated lines, not additional words.
        content = _LRC_TIME.sub('', raw).strip()
        if not content:
            continue
        for match in matches:
            rows.append((_stamp(match), content))
            if len(rows) > MAX_LINES:
                raise ValueError('Too many lyric lines')
    rows.sort(key=lambda row: row[0])
    lines, has_words = [], False
    for index, (raw_start, content) in enumerate(rows):
        raw_end = rows[index + 1][0] if index + 1 < len(rows) else max(raw_start, duration_ms + offset)
        markers = list(_WORD_TIME.finditer(content))
        if len(markers) > MAX_WORDS:
            raise ValueError('Too many lyric words')
        start, end = max(0, raw_start - offset), max(0, raw_end - offset)
        if markers:
            # Untimed prose before the first marker cannot be assigned a word time.
            if content[:markers[0].start()].strip():
                raise ValueError('Untimed prefix in enhanced LRC')
            words = []
            previous = -1
            for word_index, marker in enumerate(markers):
                word_start = _stamp(marker)
                if word_start < previous:
                    raise ValueError('Out-of-order enhanced LRC words')
                previous = word_start
                next_marker = markers[word_index + 1] if word_index + 1 < len(markers) else None
                fragment = content[marker.end():next_marker.start() if next_marker else len(content)]
                word_end = _stamp(next_marker) if next_marker else raw_end
                if fragment:
                    if word_start < raw_start or word_end < word_start:
                        raise ValueError('Enhanced LRC word outside its line')
                    words.append(_word(fragment, max(0, word_start - offset), max(0, word_end - offset)))
            if not words:
                continue
            end = max(end, max(word['endMs'] for word in words))
            has_words = True
        else:
            words = [_word(content, start, end)]
        lines.append(_line(words, start, end))
    return {'syncType': 'word' if has_words else 'line', 'lines': lines}


def _xml(text):
    if re.search(r'<!\s*(?:DOCTYPE|ENTITY)\b', text, re.I):
        raise ValueError('DTD/entities are not supported in lyrics')
    try:
        root = ET.fromstring(text)
    except (ET.ParseError, ValueError) as exc:
        raise ValueError('Invalid lyrics XML') from exc
    stack, count = [(root, 0)], 0
    while stack:
        element, depth = stack.pop()
        count += 1
        if count > MAX_WORDS + MAX_LINES or depth > 128:
            raise ValueError('Too many XML nodes or nesting levels')
        stack.extend((child, depth + 1) for child in element)
    return root


def _local(tag):
    return str(tag).rsplit('}', 1)[-1]


def _clock(value, parent_start=0, frame_rate=30, tick_rate=1):
    if value is None:
        return None
    value = str(value).strip()
    offset = re.fullmatch(r'(\d+(?:\.\d+)?)(h|m|s|ms|f|t)', value)
    if offset:
        amount, unit = float(offset[1]), offset[2]
        factor = {'h': 3600000, 'm': 60000, 's': 1000, 'ms': 1, 'f': 1000 / frame_rate, 't': 1000 / tick_rate}[unit]
        return parent_start + amount * factor
    clock = re.fullmatch(r'(?:(\d+):)?(\d{1,2}):(\d{2})(?:[.,](\d+)|:(\d{2}))?', value)
    if not clock:
        raise ValueError('Invalid TTML time expression')
    hour, minute, second, fraction, frame = clock.groups()
    if int(minute) >= 60 or int(second) >= 60 or frame and int(frame) >= frame_rate:
        raise ValueError('Invalid TTML clock')
    return int(hour or 0) * 3600000 + int(minute) * 60000 + int(second) * 1000 + (float('0.' + fraction) * 1000 if fraction else 0) + (int(frame) * 1000 / frame_rate if frame else 0)


def _ttml(text):
    root = _xml(text)
    attrs = {_local(key): value for key, value in root.attrib.items()}
    try:
        frame_rate = float(attrs.get('frameRate', 30))
        multiplier = attrs.get('frameRateMultiplier', '1 1').split()
        if len(multiplier) != 2:
            raise ValueError('Invalid TTML frame rate multiplier')
        frame_rate *= float(multiplier[0]) / float(multiplier[1])
        tick_rate = float(attrs.get('tickRate', 1))
    except (ValueError, TypeError, ZeroDivisionError) as exc:
        raise ValueError('Invalid TTML frame rate') from exc
    if not math.isfinite(frame_rate) or frame_rate <= 0 or frame_rate > 240:
        raise ValueError('Invalid TTML frame rate')
    if not math.isfinite(tick_rate) or tick_rate <= 0:
        raise ValueError('Invalid TTML tick rate')
    lines, has_words = [], False

    def bounds(element, parent_start=0, parent_end=None):
        start = _clock(element.get('begin'), parent_start, frame_rate, tick_rate)
        start = parent_start if start is None else start
        end = _clock(element.get('end'), parent_start, frame_rate, tick_rate)
        if end is None and element.get('dur'):
            end = _clock(element.get('dur'), 0, frame_rate, tick_rate) + start
        return start, parent_end if end is None else end

    def ignored(element):
        roles = [value for key, value in element.attrib.items() if _local(key) == 'role']
        return any(value in ('x-translation', 'x-roman', 'x-romanization') for value in roles)

    def background(element):
        return any(_local(key) == 'role' and value == 'x-bg' for key, value in element.attrib.items())

    def full_text(element):
        pieces = [element.text or '']
        for child in element:
            if not ignored(child) and not background(child):
                pieces.append('\n' if _local(child.tag) == 'br' else full_text(child))
            pieces.append(child.tail or '')
        return ''.join(pieces)

    def visit(element, parent_start=0, parent_end=None):
        nonlocal has_words
        if ignored(element):
            return
        start, end = bounds(element, parent_start, parent_end)
        if _local(element.tag) == 'p':
            emit_line(element, start, end)
            return
        for child in element:
            visit(child, start, end)

    def emit_line(element, start, end, is_background=False):
        nonlocal has_words
        fragments, untimed, backgrounds = [], [], []

        def spans(node, node_start, node_end, timed=False):
            timed_descendants = any(child.get('begin') is not None for child in node.iter() if child is not node)
            if timed and not timed_descendants and not any(background(child) for child in node):
                fragment = full_text(node)
                if fragment:
                    fragments.append(_word(fragment, node_start, node_end))
                return
            if node.text:
                if timed:
                    fragments.append(_word(node.text, node_start, node_end))
                elif node.text.strip():
                    untimed.append(node.text)
                elif fragments:
                    fragments[-1]['text'] += node.text
            for child in node:
                if background(child):
                    child_start, child_end = bounds(child, node_start, node_end)
                    backgrounds.append((child, child_start, child_end))
                elif not ignored(child):
                    child_start, child_end = bounds(child, node_start, node_end)
                    child_timed = timed or (child.get('begin') is not None and (child.get('end') is not None or child.get('dur') is not None))
                    if _local(child.tag) == 'br':
                        if fragments:
                            fragments[-1]['text'] += '\n'
                    else:
                        spans(child, child_start, child_end, child_timed)
                if child.tail:
                    if child.tail.strip():
                        if timed:
                            fragments.append(_word(child.tail, node_start, node_end))
                        else:
                            untimed.append(child.tail)
                    elif fragments:
                        fragments[-1]['text'] += child.tail

        spans(element, start, end)
        content = full_text(element).strip()
        if not content:
            for child, child_start, child_end in backgrounds:
                emit_line(child, child_start, child_end, True)
            return
        if fragments and not untimed:
            if element.get('begin') is None:
                start = min(word['startMs'] for word in fragments)
            if end is None:
                end = max(word['endMs'] for word in fragments)
            lines.append(_line(fragments, start, end))
            has_words = True
        else:
            if end is None:
                raise ValueError('TTML line has no end time')
            lines.append(_line([_word(content, start, end)], start, end))
        if is_background:
            lines[-1]['background'] = True
        for child, child_start, child_end in backgrounds:
            emit_line(child, child_start, child_end, True)

    visit(root)
    lines.sort(key=lambda line: line['startMs'])
    return {'syncType': 'syllable' if has_words else 'line', 'lines': lines}


def _numeric_lyrics(text, format):
    if text.lstrip().startswith('<'):
        root = _xml(text)
        payloads = [element.get('LyricContent') for element in root.iter() if element.get('LyricContent')]
        if not payloads:
            raise ValueError('Missing QRC lyric content')
        text = '\n'.join(payloads)
    lines = []
    pattern = re.compile(r'\((\d+),(\d+)' + (r',\d+' if format == 'yrc' else '') + r'\)')
    # QQ sometimes emits literal newlines inside an XML attribute. XML
    # parsers correctly normalize those to spaces; numeric line headers are
    # still unambiguous and must not disappear with the original line breaks.
    headers = list(re.finditer(r'\[(\d+),(\d+)\]', text))
    if len(headers) > MAX_LINES:
        raise ValueError('Too many lyric lines')
    for index, header in enumerate(headers):
        start, length = map(int, header.groups())
        end = start + length
        stop = headers[index + 1].start() if index + 1 < len(headers) else len(text)
        content = text[header.end():stop].rstrip()
        markers = list(pattern.finditer(content))
        if len(markers) > MAX_WORDS:
            raise ValueError('Too many lyric words')
        words = []
        if format == 'yrc':
            if markers and content[:markers[0].start()].strip():
                raise ValueError('Untimed YRC prefix')
            for index, marker in enumerate(markers):
                stop = markers[index + 1].start() if index + 1 < len(markers) else len(content)
                word_start, word_length = map(int, marker.groups())
                fragment = content[marker.end():stop]
                if fragment:
                    words.append(_word(fragment, word_start, word_start + word_length))
        else:
            position = 0
            for marker in markers:
                fragment = content[position:marker.start()]
                word_start, word_length = map(int, marker.groups())
                if fragment:
                    words.append(_word(fragment, word_start, word_start + word_length))
                position = marker.end()
            if content[position:].strip():
                raise ValueError('Untimed QRC suffix')
        if words:
            lines.append(_line(words, start, end))
    lines.sort(key=lambda line: line['startMs'])
    return {'syncType': 'word', 'lines': lines}


def parse_lyrics(text, format, duration_ms=0):
    """Parse source text or raise ValueError for malformed, unsafe or empty data."""
    duration_ms = _duration(duration_ms)
    if not isinstance(text, str) or len(text.encode('utf-8')) > MAX_INPUT_BYTES:
        raise ValueError('Invalid or oversized lyrics input')
    format = str(format or '').casefold().replace('-', '_')
    if format == 'auto':
        format = 'ttml' if re.search(r'<(?:\w+:)?tt\b', text) else 'lrc' if _LRC_TIME.search(text) else 'plain'
    if format == 'ttml':
        result = _ttml(text)
    elif format in ('qrc', 'yrc'):
        result = _numeric_lyrics(text, format)
    elif format in ('lrc', 'enhanced_lrc', 'elrc', 'richsync'):
        result = _lrc(text, duration_ms)
    elif format in ('plain', 'text', 'txt'):
        result = _plain(text)
    else:
        raise ValueError('Unsupported lyrics format')
    if not validate_lyrics(result, duration_ms):
        raise ValueError('Invalid lyrics timing or content')
    return result


def plain_text(model):
    """Human-readable text without discarding spaces or combining syllables wrongly."""
    if not validate_lyrics(model):
        raise ValueError('Invalid lyrics model')
    return '\n'.join(''.join(word['text'] for word in line['words']).strip() for line in model['lines'])


def to_lrc(model):
    """Line-only compatibility view; the normalized model retains richer timing."""
    if not validate_lyrics(model):
        raise ValueError('Invalid lyrics model')
    if model['syncType'] == 'plain':
        return plain_text(model)
    rows = []
    for line in model['lines']:
        timestamp = max(0, round(line['startMs']))
        minute, remainder = divmod(timestamp, 60000)
        second, milliseconds = divmod(remainder, 1000)
        rows.append(f'[{minute:02}:{second:02}.{milliseconds:03}] ' + ''.join(word['text'] for word in line['words']).strip())
    return '\n'.join(rows)
