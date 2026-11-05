"""Regression tests for the shared matching fixes (BUG-A1-011, BUG-L2-004, BUG-S4-010)."""
from services.music_matching import VERSION_PATTERNS, artist_matches, similarity, title_metadata


def test_radio_edit_is_a_version():
    meta = title_metadata('Song (Radio Edit)')
    assert meta['version'] == 'remix', meta
    assert meta['base_title'] == 'Song', meta


def test_extended_mix_is_a_version():
    # Dash qualifier needs artist context, otherwise "Song - Extended Mix"
    # is legitimately parsed as "Artist - Title".
    meta = title_metadata('Song - Extended Mix', 'Artist')
    assert meta['version'] == 'remix', meta
    assert meta['base_title'] == 'Song', meta


def test_club_mix_is_a_version():
    assert title_metadata('Song (Club Mix)')['version'] == 'remix'


def test_plain_title_has_no_version():
    assert title_metadata('Song (I Love You)')['version'] == ''


def test_short_titles_do_not_match_by_containment():
    # BUG-L2-004: "Ты" is a word of "Ты и я" but a different song.
    assert similarity('Ты', 'Ты и я') < 0.85
    assert similarity('Hey', 'Hey Ya') < 0.85
    assert similarity('DNA', 'DNA Remix') < 0.85


def test_short_titles_still_match_exactly():
    assert similarity('Ты!', 'ты') == 1.0
    # Longer titles keep the fuzzy path.
    assert similarity('Полковнику никто не пишет', 'полковнику никто не пишет') == 1.0


def test_life_vs_live_stays_zero():
    assert similarity('Life', 'Live') == 0


def test_solo_artist_does_not_auto_match_duo():
    # BUG-S4-010: single credit must not open a duo's catalog.
    assert not artist_matches('Miyagi', 'Miyagi & Andy Panda')
    assert not artist_matches(['Miyagi'], [{'name': 'Miyagi & Andy Panda'}])


def test_duo_matches_duo_regardless_of_order_or_separators():
    assert artist_matches('Miyagi & Andy Panda', 'Andy Panda, Miyagi')
    assert artist_matches('A feat. B', 'B feat. A')


def test_solo_still_matches_solo():
    assert artist_matches('Miyagi', 'miyagi')
    assert artist_matches('PHARAOH', 'фараон')  # default alias


def test_multicredit_requires_full_set_both_directions():
    assert not artist_matches('A feat. B', 'A')  # under-credited recording is a different entity
