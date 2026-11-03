"""Comprehensive verification and regression tests for Group #4:
Lyrics, metadata cleaning, version fallbacks, word sync, and LRC formats.

Covers:
- BUG-WIN-004: Expanded duration tolerance (6s for synced, 15s for plain)
- BUG-WIN-013: Fallback for Live/Acoustic/Cover and studio marker cleaning (Remaster/Deluxe/OST)
- BUG-WIN-014: LRCLIB title-based fallback search for Latin tracks on artist mismatch
- BUG-WIN-015: Robust word-engine timing normalization (no reset on word timing discrepancy or overlaps)
- BUG-WIN-038: 4-digit subsecond fractional timecodes in LRC and enhanced LRC
- BUG-WIN-039: Repeated chorus line-by-line translation mapping
"""
import json
import urllib.parse
from io import BytesIO

import pytest

from services.lyrics_formats import parse_lyrics
from services.lyrics_metadata import lyrics_metadata
from services.lyrics_service import LyricsService
from services.music_matching import BASE_FALLBACK_VERSIONS, similarity, title_metadata
from tests.jsdom import run_node, source


# ---------------------------------------------------------------------------
# BUG-WIN-004: Duration tolerance expansion (6s synced, 15s plain)
# ---------------------------------------------------------------------------

def test_lyrics_lookup_accepts_delta_up_to_6_seconds_for_synced():
    service = LyricsService()
    form = {
        'metadata': lyrics_metadata('Starboy', 'The Weeknd'),
        'duration': 230,
        'fallback': False,
    }
    synced_lrc = '[00:01.00]I am a starboy\n[00:05.00]Next line'

    # Candidate with +5.0s delta (235s vs wanted 230s) -> within 6s -> syncedLyrics preserved
    result = service._lookup.accept(form, 'Starboy', 'The Weeknd', 235, synced_lrc, None, 'LRCLIB')
    assert result is not None
    assert result['status'] == 'found'
    assert result['syncedLyrics'] == synced_lrc
    assert result['weight'] == 1


def test_lyrics_lookup_accepts_delta_between_6_and_15_seconds_as_plain():
    service = LyricsService()
    form = {
        'metadata': lyrics_metadata('Starboy', 'The Weeknd'),
        'duration': 230,
        'fallback': False,
    }
    synced_lrc = '[00:01.00]I am a starboy\n[00:05.00]Next line'

    # Candidate with +10.0s delta (240s vs wanted 230s) -> > 6s but <= 15s -> fallback to plainLyrics
    result = service._lookup.accept(form, 'Starboy', 'The Weeknd', 240, synced_lrc, None, 'LRCLIB')
    assert result is not None
    assert result['status'] == 'found'
    assert result['syncedLyrics'] is None
    assert 'I am a starboy' in result['plainLyrics']
    assert 'Next line' in result['plainLyrics']
    assert result['weight'] == 2


def test_lyrics_lookup_rejects_delta_exceeding_15_seconds():
    service = LyricsService()
    form = {
        'metadata': lyrics_metadata('Starboy', 'The Weeknd'),
        'duration': 230,
        'fallback': False,
    }
    synced_lrc = '[00:01.00]I am a starboy'

    # Candidate with +25.0s delta (255s vs wanted 230s) -> exceeds 15s -> rejected
    result = service._lookup.accept(form, 'Starboy', 'The Weeknd', 255, synced_lrc, None, 'LRCLIB')
    assert result is None


def test_plain_only_lyrics_accepted_up_to_15_seconds_delta():
    service = LyricsService()
    form = {
        'metadata': lyrics_metadata('Blinding Lights', 'The Weeknd'),
        'duration': 200,
        'fallback': False,
    }
    plain_text = 'Yeah\nI been on my own for long enough'

    # Plain text candidate with +12s delta (212s vs 200s) -> <= 15s -> accepted
    result = service._lookup.accept(form, 'Blinding Lights', 'The Weeknd', 212, None, plain_text, 'Genius')
    assert result is not None
    assert result['plainLyrics'] == plain_text
    assert result['syncedLyrics'] is None


# ---------------------------------------------------------------------------
# BUG-WIN-013: Fallback for Live/Acoustic/Cover and studio marker cleaning
# ---------------------------------------------------------------------------

def test_base_fallback_versions_contains_live_acoustic_cover():
    assert 'live' in BASE_FALLBACK_VERSIONS
    assert 'acoustic' in BASE_FALLBACK_VERSIONS
    assert 'cover' in BASE_FALLBACK_VERSIONS
    assert 'sped' in BASE_FALLBACK_VERSIONS
    assert 'slowed' in BASE_FALLBACK_VERSIONS
    assert 'remix' in BASE_FALLBACK_VERSIONS


@pytest.mark.parametrize('version_marker', ['Live', 'Acoustic', 'Cover'])
def test_fallback_accepts_studio_lyrics_for_live_acoustic_cover(version_marker):
    service = LyricsService()
    form = {
        'metadata': lyrics_metadata(f'Hotel California ({version_marker})', 'Eagles'),
        'duration': 390,
        'fallback': True,
    }
    # Studio candidate has no version (empty string)
    result = service._lookup.accept(form, 'Hotel California', 'Eagles', 390, None, 'On a dark desert highway', 'LRCLIB')
    assert result is not None
    assert result['match_type'] == 'base'
    assert result['plainLyrics'] == 'On a dark desert highway'


@pytest.mark.parametrize('raw_title,expected_clean', [
    ('Bohemian Rhapsody (2011 Remaster)', 'Bohemian Rhapsody'),
    ('Bohemian Rhapsody (Remastered 2021)', 'Bohemian Rhapsody'),
    ('Bohemian Rhapsody [2011 Remastered]', 'Bohemian Rhapsody'),
    ('Bohemian Rhapsody - 2011 Remaster', 'Bohemian Rhapsody'),
    ('Bohemian Rhapsody - Remastered', 'Bohemian Rhapsody'),
    ('Megalovania [OST]', 'Megalovania'),
    ('Main Theme (Original Soundtrack)', 'Main Theme'),
    ('Radio Ga Ga (Deluxe Edition)', 'Radio Ga Ga'),
    ('Radio Ga Ga [Deluxe]', 'Radio Ga Ga'),
    ('Thriller (Anniversary Edition)', 'Thriller'),
])
def test_lyrics_metadata_cleans_studio_and_edition_markers(raw_title, expected_clean):
    meta = lyrics_metadata(raw_title, 'Queen')
    assert meta['title'] == expected_clean
    assert meta['base_title'] == expected_clean
    assert meta['version'] == ''
    assert similarity(meta['base_title'], expected_clean) == 1.0


# ---------------------------------------------------------------------------
# BUG-WIN-014: LRCLIB fallback search by title for Latin tracks
# ---------------------------------------------------------------------------

def test_lrclib_title_search_fallback_on_artist_mismatch_for_latin_tracks(monkeypatch):
    """When a Latin track's artist in local metadata does not match LRCLIB's exact artist name,
    _lrclib_query (/api/get and /api/search?q=...) fails. The fallback search by track_name
    must be triggered and successfully match via _artists_agree.
    """
    service = LyricsService()
    for name in ('netease', 'qqmusic', 'genius', 'megalobiz'):
        monkeypatch.setattr(service._lookup, name, lambda *a: None)

    requests = []

    def open_url(request, **kwargs):
        parsed = urllib.parse.urlsplit(request.full_url)
        query = urllib.parse.parse_qs(parsed.query)
        requests.append((parsed.path, query))
        # LRCLIB exact GET /api/get misses
        if parsed.path == '/api/get':
            return BytesIO(b'{}')
        # Direct q search with mismatching artist misses
        if 'q' in query:
            return BytesIO(b'[]')
        # Title search /api/search?track_name=Get Lucky returns matching candidate
        if query.get('track_name') == ['Get Lucky']:
            rows = [{
                'trackName': 'Get Lucky',
                'artistName': 'Daft Punk',
                'duration': 248,
                'plainLyrics': 'Like the legend of the phoenix',
                'syncedLyrics': '[00:01.00] Like the legend of the phoenix',
            }]
            return BytesIO(json.dumps(rows).encode())
        return BytesIO(b'[]')

    monkeypatch.setattr(service, '_open_url', open_url)

    # Local metadata has credit 'Daft Punk feat. Pharrell Williams'
    actual = service.get_lyrics('Get Lucky', 'Daft Punk feat. Pharrell Williams', 248000)
    assert actual['status'] == 'found'
    assert actual['matched_artist'] == 'Daft Punk'
    assert 'Like the legend' in actual['plainLyrics']
    # Verify that track_name query was executed
    assert any(q.get('track_name') == ['Get Lucky'] for _, q in requests)


# ---------------------------------------------------------------------------
# BUG-WIN-015: Word timing normalization (no reset on word timing discrepancy)
# ---------------------------------------------------------------------------

def test_word_engine_clamps_word_timing_discrepancy_without_resetting():
    run_node(r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';
const ctx = vm.createContext({});
vm.runInContext(ENGINE.replaceAll('export ', ''), ctx);

// Case 1: Word exceeds line endMs by 20ms (e.g. line 1000-2000, word 1000-2020)
const lineOver = {
    startMs: 1000,
    endMs: 2000,
    words: [{text: 'Hello ', startMs: 1000, endMs: 2020}]
};
const res1 = ctx.normalizedTimedLines({syncType: 'word', lines: [lineOver]});
assert.equal(res1.length, 1, 'line must not be dropped due to minor word overshoot');
assert.equal(res1[0].words[0].endMs, 2000, 'word endMs must be clamped to line endMs');

// Case 2: Word starts 10ms before line startMs (e.g. line 1000-2000, word 990-1500)
const lineUnder = {
    startMs: 1000,
    endMs: 2000,
    words: [{text: 'World ', startMs: 990, endMs: 1500}]
};
const res2 = ctx.normalizedTimedLines({syncType: 'word', lines: [lineUnder]});
assert.equal(res2.length, 1, 'line must not be dropped due to minor word undershoot');
assert.equal(res2[0].words[0].startMs, 1000, 'word startMs must be clamped to line startMs');

// Case 3: Overlapping backing vocal lines (line 2 starts before line 1 ends)
const backingLines = [
    {startMs: 2000, endMs: 5000, words: [{text: 'Lead ', startMs: 2000, endMs: 5000}]},
    {startMs: 3000, endMs: 6000, words: [{text: 'Backing ', startMs: 3000, endMs: 6000}]}
];
const res3 = ctx.normalizedTimedLines({syncType: 'word', lines: backingLines});
assert.equal(res3.length, 2, 'overlapping vocal lines must both be preserved');
assert.equal(res3[0].startMs, 2000);
assert.equal(res3[1].startMs, 3000);
""".replace('ENGINE', source('lyrics-word-engine.js')))


# ---------------------------------------------------------------------------
# BUG-WIN-038: 4-digit subsecond fractional timecodes in LRC
# ---------------------------------------------------------------------------

def test_lrc_fractional_seconds_with_4_digits_python():
    lrc_content = "[01:23.4567] This line has four fractional digits\n[01:25.80] Standard two digits"
    parsed = parse_lyrics(lrc_content, 'auto', duration_ms=100000)
    assert parsed['syncType'] == 'line'
    assert len(parsed['lines']) == 2
    # 01:23.4567 -> 1*60000 + 23*1000 + 456 = 83456 ms
    assert parsed['lines'][0]['startMs'] == 83456
    assert parsed['lines'][0]['words'][0]['text'] == 'This line has four fractional digits'


def test_enhanced_lrc_word_time_with_4_digits_python():
    enhanced_lrc = "[01:00.00] <01:00.1234>Hello <01:00.5678>World"
    parsed = parse_lyrics(enhanced_lrc, 'auto', duration_ms=70000)
    assert parsed['syncType'] == 'word'
    words = parsed['lines'][0]['words']
    assert len(words) == 2
    assert words[0]['startMs'] == 60123
    assert words[1]['startMs'] == 60567


def test_parse_lrc_js_with_4_digit_fractions():
    run_node(r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';
const ctx = vm.createContext({window: {}});
const code = SOURCE;
const start = code.indexOf('export function parseLrc(');
const end = code.indexOf('\n/**', start);
vm.runInContext(code.slice(start, end).replace('export ', ''), ctx);

const lrc = '[01:23.4567] Line with 4 digits\n[02:00.12] Line with 2 digits';
const res = ctx.parseLrc(lrc);
assert.equal(res.length, 2);
assert.equal(res[0].timeMs, 83456);
assert.equal(res[0].text, 'Line with 4 digits');
assert.equal(res[1].timeMs, 120120);
""".replace('SOURCE', source('lyrics.js')))


# ---------------------------------------------------------------------------
# BUG-WIN-039: Repeated chorus line-by-line translation mapping
# ---------------------------------------------------------------------------

def test_repeated_chorus_translation_mapping_preserves_per_line_translations():
    run_node(r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';
class CustomEvent { constructor(type, opts) { this.type = type; this.detail = opts?.detail; } }
const events = [];
function element() { return {classList: {toggle() {}, add() {}, remove() {}}, style: {}, disabled: false, addEventListener() {}}; }

let resolveApi;
const context = vm.createContext({
    console, CustomEvent, setTimeout, clearTimeout,
    parsedLyrics: [
        {text: 'Tell me why', timeMs: 10000},
        {text: 'Ain\'t nothin\' but a heartache', timeMs: 13000},
        {text: 'Tell me why', timeMs: 16000},
    ],
    currentTranslationMap: {},
    isTranslationEnabled: false,
    currentRawLyricsText: 'Tell me why\nAin\'t nothin\' but a heartache\nTell me why',
    lastLyricsData: {
        syncedLyrics: '[00:10.00] Tell me why\n[00:13.00] Ain\'t nothin\' but a heartache\n[00:16.00] Tell me why',
        plainLyrics: null,
    },
    lastLoadedTrackKey: 'track-bsp',
    cleanPlainLyrics: text => String(text || '').replace(/\[[^\]]*\]/g, '').split(/\r?\n/).map(l => l.trim()).filter(Boolean),
    renderLyrics() {},
    document: {getElementById: () => element()},
    window: {
        dispatchEvent: e => events.push(e),
        pywebview: {api: {
            get_lyrics_translation: () => new Promise(r => { resolveApi = r; }),
        }},
    },
});

const code = SOURCE;
vm.runInContext(code.slice(code.indexOf('function buildTranslationMap('), code.indexOf('export function updateOffsetBadges(')).replace('export ', ''), context);
context.toggleTranslation(true);

// Backend translates line 0 and line 2 (chorus) with slight contextual variations
resolveApi({
    success: true,
    text: 'Скажи мне почему\nНичего кроме сердечной боли\nСкажи мне, почему же',
    error: null,
});

await new Promise(r => setTimeout(r, 20));

// Verification: index 0 and index 2 must have distinct per-line translations
assert.equal(context.currentTranslationMap[0], 'Скажи мне почему');
assert.equal(context.currentTranslationMap[1], 'Ничего кроме сердечной боли');
assert.equal(context.currentTranslationMap[2], 'Скажи мне, почему же');

// Text-key fallback is also present
assert.ok(context.currentTranslationMap['Tell me why']);
""".replace('SOURCE', source('lyrics.js')))
