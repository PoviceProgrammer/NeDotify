"""Real timed fixtures and hostile-input checks for normalized lyric parsers."""
import copy
import math

import pytest

from services.lyrics_formats import parse_lyrics, plain_text, to_lrc, validate_lyrics


def test_ttml_preserves_real_syllable_intervals_and_spaces():
    text = '''<tt xmlns="http://www.w3.org/ns/ttml"><body><div><p begin="00:01.000" end="00:03.000"><span begin="00:01.000" end="00:01.250">При</span><span begin="00:01.250" end="00:02.000">вет </span><span begin="00:02.000" end="00:03.000">мир!</span></p></div></body></tt>'''
    result = parse_lyrics(text, 'ttml', 3000)
    assert result['syncType'] == 'syllable'
    assert [(w['startMs'], w['endMs']) for w in result['lines'][0]['words']] == [(1000, 1250), (1250, 2000), (2000, 3000)]
    assert plain_text(result) == 'Привет мир!'
    assert to_lrc(result) == '[00:01.000] Привет мир!'


def test_ttml_line_only_does_not_claim_word_timing():
    result = parse_lyrics('<tt><body><p begin="1s" end="2s">Hello world</p></body></tt>', 'ttml')
    assert result['syncType'] == 'line'
    assert len(result['lines'][0]['words']) == 1


def test_ttml_relative_offset_and_parallel_background_lines():
    result = parse_lyrics('''<tt><body><div begin="10s"><p begin="1s" dur="2s"><span begin="0s" dur="1s">Да</span><span begin="1s" dur="1s">!</span></p><p begin="1s" end="3s">фон</p></div></body></tt>''', 'ttml')
    assert [line['startMs'] for line in result['lines']] == [11000, 11000]
    assert result['lines'][0]['words'][1]['startMs'] == 12000


def test_ttml_translation_not_sung_as_part_of_original():
    result = parse_lyrics('''<tt xmlns:ttm="http://www.w3.org/ns/ttml#metadata"><body><p begin="00:01" end="00:02"><span begin="00:01" end="00:02">Hello</span><span ttm:role="x-translation">Привет</span></p></body></tt>''', 'ttml')
    assert plain_text(result) == 'Hello'


def test_ttml_background_vocals_have_independent_overlapping_word_timelines():
    result = parse_lyrics('''<tt xmlns:ttm="http://www.w3.org/ns/ttml#metadata"><body><p begin="00:01" end="00:03"><span begin="00:01" end="00:03">Main</span><span ttm:role="x-bg" begin="00:01.5" end="00:02.5"><span begin="00:01.5" end="00:02">Back </span><span begin="00:02" end="00:02.5">ground</span></span></p></body></tt>''', 'ttml')
    assert len(result['lines']) == 2
    assert result['lines'][1]['background'] is True
    assert result['lines'][1]['words'][0]['startMs'] == 1500


def test_ttml_tick_rate_and_inferred_line_bounds():
    result = parse_lyrics('''<tt xmlns:ttp="http://www.w3.org/ns/ttml#parameter" ttp:tickRate="100"><body><p><span begin="100t" end="200t">Hello</span></p></body></tt>''', 'ttml')
    assert result['lines'][0]['startMs'] == 1000
    assert result['lines'][0]['endMs'] == 2000


def test_ttml_untimed_nested_markup_does_not_invent_independent_word_spans():
    result = parse_lyrics('''<tt><body><p begin="00:01" end="00:02"><span begin="00:01" end="00:02"><span>Hel</span><span>lo</span></span></p></body></tt>''', 'ttml')
    assert len(result['lines'][0]['words']) == 1
    assert plain_text(result) == 'Hello'


def test_qrc_xml_contains_absolute_word_times():
    text = '<QrcInfos><LyricInfo><Lyric_1 LyricContent="[1000,2000]При(1000,250)вет (1250,750)мир(2000,1000)"/></LyricInfo></QrcInfos>'
    result = parse_lyrics(text, 'qrc')
    assert result['syncType'] == 'word'
    assert plain_text(result) == 'Привет мир'
    assert result['lines'][0]['words'][1]['startMs'] == 1250


def test_yrc_preserves_short_word_durations():
    result = parse_lyrics('[1000,2000](1000,1,0)Я (1001,999,0)здесь (2000,1000,0)now', 'yrc')
    assert result['syncType'] == 'word'
    assert plain_text(result) == 'Я здесь now'
    assert result['lines'][0]['words'][0]['endMs'] == 1001


def test_enhanced_lrc_uses_actual_markers_not_equal_word_durations():
    result = parse_lyrics('[00:01.00]<00:01.00>Hello <00:01.10>world<00:03.00>', 'enhanced_lrc', 3000)
    assert result['syncType'] == 'word'
    words = result['lines'][0]['words']
    assert [(w['startMs'], w['endMs']) for w in words] == [(1000, 1100), (1100, 3000)]


def test_lrc_multiple_stamps_offset_and_plain_fallback():
    result = parse_lyrics('[offset:500]\n[00:01.00][00:03.00]Привет мир\n[00:05.00]Последняя', 'lrc', 7000)
    assert result['syncType'] == 'line'
    assert [line['startMs'] for line in result['lines']] == [500, 2500, 4500]
    assert len(result['lines'][0]['words']) == 1
    plain = parse_lyrics('Привет & <мир>\nHello!', 'plain')
    assert plain['syncType'] == 'plain'
    assert plain_text(plain) == 'Привет & <мир>\nHello!'


@pytest.mark.parametrize('text,format', [
    ('[1000,100]bad(1000,200)', 'qrc'),
    ('[1000,1000](2000,100,0)bad', 'yrc'),
    ('[1000,1000](1500,100,0)a(1000,100,0)b', 'yrc'),
    ('[00:01]<00:02>a<00:01>b', 'enhanced_lrc'),
    ('[00:99]bad', 'lrc'),
    ('<tt><body><p begin="NaN" end="2s">bad</p></body></tt>', 'ttml'),
    ('<tt><body><p begin="3s" end="2s">bad</p></body></tt>', 'ttml'),
    ('<!DOCTYPE tt [<!ENTITY x "boom">]><tt>&x;</tt>', 'ttml'),
    ('<QrcInfos/>', 'qrc'),
    ('', 'plain'),
])
def test_invalid_or_unsafe_source_rejected(text, format):
    with pytest.raises(ValueError):
        parse_lyrics(text, format)


@pytest.mark.parametrize('value', [math.nan, math.inf, -1, True, '100'])
def test_normalized_cache_payload_rejects_invalid_timestamps(value):
    result = parse_lyrics('[00:01]Hello', 'lrc', 2000)
    result['lines'][0]['words'][0]['startMs'] = value
    assert not validate_lyrics(result)


def test_timing_far_outside_track_is_rejected():
    with pytest.raises(ValueError):
        parse_lyrics('[1000,60000](1000,60000,0)Wrong version', 'yrc', 3000)


def test_normalized_payload_survives_json_and_validation_does_not_mutate():
    import json
    result = parse_lyrics('[1000,1000]Да(1000,0)!(1000,1000)', 'qrc')
    original = copy.deepcopy(result)
    assert validate_lyrics(json.loads(json.dumps(result)))
    assert result == original


def test_limits_bound_input_and_parsed_line_count():
    with pytest.raises(ValueError):
        parse_lyrics('x' * (2 * 1024 * 1024 + 1), 'plain')
    with pytest.raises(ValueError):
        parse_lyrics('hello\n' * 5001, 'plain')
