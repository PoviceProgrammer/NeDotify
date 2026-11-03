"""Regression coverage for upload editions and Russian catalogue recovery."""
import json
import urllib.parse
from io import BytesIO

import pytest

from services.lyrics_service import LyricsService
from services.lyrics_metadata import lyrics_metadata
from tests.jsdom import run_node, source


def test_video_duration_mismatch_keeps_source_timestamps_and_removes_credit_headers():
    service = LyricsService()
    raw = '[00:00] 作词 : Artist\n[00:01] Hello'
    form = {'metadata': lyrics_metadata('A Song (official video)', 'Artist'), 'duration': 263}
    result = service._lookup.accept(form, 'A Song', 'Artist', 200.727, raw, None, 'Netease')
    assert result['plainLyrics'] == 'Hello'
    assert result['syncedLyrics'] is None
    assert result['originalLyrics'] == raw and result['originalFormat'] == 'lrc'


@pytest.mark.parametrize('suffix', ['slowed', 'slowed + reverb', 'sped up', 'Remix', 'ремикс'])
def test_unbracketed_upload_version_finds_plain_original(monkeypatch, suffix):
    service = LyricsService()
    for name in ('netease', 'qqmusic', 'genius', 'megalobiz'):
        monkeypatch.setattr(service._lookup, name, lambda *a: None)
    row = {'trackName': 'A Song', 'artistName': 'Artist', 'duration': 120,
           'plainLyrics': 'Hello', 'syncedLyrics': '[00:01] Hello'}
    monkeypatch.setattr(service._lookup, '_json', lambda url, *a: [row] if '/search?' in url else row)
    result = service.get_lyrics(f'A Song {suffix}', 'Artist', 180000)
    assert result['plainLyrics'] == 'Hello'
    assert result['match_type'] == 'base' and result['syncedLyrics'] is None


@pytest.mark.parametrize('marker', ['Official Video', 'Официальный клип', 'Official Music Video 4K'])
def test_video_intro_keeps_text_without_album_timing(monkeypatch, marker):
    service = LyricsService()
    for name in ('netease', 'qqmusic', 'genius', 'megalobiz'):
        monkeypatch.setattr(service._lookup, name, lambda *a: None)
    row = {'trackName': 'A Song', 'artistName': 'Artist', 'duration': 120,
           'plainLyrics': 'Hello', 'syncedLyrics': '[00:01] Hello'}
    monkeypatch.setattr(service._lookup, '_json', lambda url, *a: [row] if '/search?' in url else row)
    result = service.get_lyrics(f'A Song ({marker})', 'Artist', 150000)
    assert result['plainLyrics'] == 'Hello' and result['syncedLyrics'] is None


@pytest.mark.parametrize('provider', ['genius', 'qqmusic', 'megalobiz'])
def test_every_source_can_search_original_for_remix(monkeypatch, provider):
    service = LyricsService()
    for name in ('lrclib', 'netease', 'qqmusic', 'genius', 'megalobiz'):
        monkeypatch.setattr(service._lookup, name, lambda *a: None)
    def original(form, *args):
        if form['query_title'] == 'A Song':
            return service._lookup.accept(form, 'A Song', 'Artist', 120, None, 'Hello', provider)
    monkeypatch.setattr(service._lookup, provider, original)
    result = service.get_lyrics('A Song (Remix)', 'Artist', 180000)
    assert result['plainLyrics'] == 'Hello' and result['match_type'] == 'base'


@pytest.mark.parametrize('title,duration', [('Апрель (slowed)', 180000), ('Апрель', 120000)])
def test_russian_title_only_catalogue_within_request_cap(monkeypatch, title, duration):
    service = LyricsService()
    for name in ('netease', 'qqmusic', 'genius', 'megalobiz'):
        monkeypatch.setattr(service._lookup, name, lambda *a: None)
    queries = []
    def request(req, **kwargs):
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(req.full_url).query)
        queries.append(query)
        rows = [{'trackName': 'Апрель', 'artistName': 'Other', 'duration': 120, 'plainLyrics': 'Wrong'},
                {'trackName': 'Апрель', 'artistName': 'Skriptonit', 'duration': 120, 'plainLyrics': 'Right'}]
        payload = rows if query == {'track_name': ['Апрель']} else ([] if '/search?' in req.full_url else {})
        return BytesIO(json.dumps(payload).encode())
    monkeypatch.setattr(service, '_open_url', request)
    result = service.get_lyrics(title, 'Скриптонит', duration)
    assert result['plainLyrics'] == 'Right' and result['syncedLyrics'] is None
    assert len(queries) <= 4


def test_unbracketed_video_suffix_and_wrong_artist(monkeypatch):
    service = LyricsService()
    for name in ('netease', 'qqmusic', 'genius', 'megalobiz'):
        monkeypatch.setattr(service._lookup, name, lambda *a: None)
    rows = [{'trackName': 'A Song', 'artistName': 'Other Artist', 'duration': 120, 'plainLyrics': 'Wrong'},
            {'trackName': 'A Song', 'artistName': 'Artist', 'duration': 120, 'plainLyrics': 'Right'}]
    monkeypatch.setattr(service._lookup, '_json', lambda url, *a: rows if '/search?' in url else {})
    result = service.get_lyrics('A Song - Official Music Video', 'Artist', 150000)
    assert result['plainLyrics'] == 'Right' and result['syncedLyrics'] is None


def test_russian_title_keeps_original_query_then_tries_exact_transcription(monkeypatch):
    service = LyricsService()
    for name in ('netease', 'qqmusic', 'genius', 'megalobiz'):
        monkeypatch.setattr(service._lookup, name, lambda *a: None)
    queries = []
    def request(req, **kwargs):
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(req.full_url).query)
        queries.append(query)
        rows = [{'trackName': 'Aprel', 'artistName': 'Skriptonit', 'duration': 120, 'plainLyrics': 'Right'}]
        body = rows if query == {'track_name': ['aprel']} else ([] if '/search?' in req.full_url else {})
        return BytesIO(json.dumps(body).encode())
    monkeypatch.setattr(service, '_open_url', request)
    result = service.get_lyrics('Апрель', 'Скриптонит', 120000)
    assert result['plainLyrics'] == 'Right'
    assert queries[0]['track_name'] == ['Апрель']
    assert {'track_name': ['Апрель']} in queries and {'track_name': ['aprel']} in queries
    assert len(queries) <= 5


def test_lrc_colon_fraction_and_embedded_offset():
    run_node(r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';
const code = SOURCE;
const ctx = vm.createContext({});
vm.runInContext(code.slice(code.indexOf('export function parseLrc('), code.indexOf('export function updateLyricsPosition(')).replace('export ', ''), ctx);
assert.equal(ctx.parseLrc('[00:01:50] Hello')[0].timeMs, 1500);
assert.equal(ctx.parseLrc('[offset:500]\n[00:01.00] Hello')[0].timeMs, 500);
assert.equal(ctx.parseLrc('[offset:-500]\n[00:01.00] Hello')[0].timeMs, 1500);
""".replace('SOURCE', source('lyrics.js')))


def test_clicking_line_applies_user_offset_to_seek():
    run_node(r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';
let clicked, seekPosition;
function element() {return {dataset: {}, appendChild() {}, addEventListener(name, fn) {if (name === 'click') clicked = fn;}};}
const context = vm.createContext({
  lastLyricsData: null, lastLyricsRevision: 0, pendingLyricsRequest: null,
  currentTranslationMap: {}, currentOffsetMs: 1500, lastPosMs: 0,
  isTranslationEnabled: false, parsedLyrics: [], currentRawLyricsText: '',
  getContainers: () => [{innerHTML: '', appendChild() {}}],
  cleanPlainLyrics: text => String(text || '').split('\n'),
  rememberLyrics() {}, resetLyricsScroll() {}, updateOffsetBadges() {},
  document: {createElement: element}, parseLrc: () => [{timeMs: 10000, text: 'Hello'}],
  updateLyricsPosition() {}, setOffsetControlsEnabled() {},
  seekTo: pos => seekPosition = pos,
  ensureKineticState: () => ({measured: false}), ensureMeasured: () => false,
  Math,
});
const code = SOURCE;
vm.runInContext(code.slice(code.indexOf('export function renderLyrics('), code.indexOf('export function parseLrc(')).replace('export ', ''), context);
context.renderLyrics({syncedLyrics: '[00:10] Hello', plainLyrics: 'Hello'});
clicked({stopPropagation() {}});
assert.equal(seekPosition, 8500);
context.currentOffsetMs = 15000;
clicked({stopPropagation() {}});
assert.equal(seekPosition, 0);
""".replace('SOURCE', source('lyrics.js')))
