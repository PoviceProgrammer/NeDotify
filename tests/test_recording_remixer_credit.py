"""Cross-catalogue remixer credits must retain named-version identity."""
import pytest

from core.playback_recovery import same_recording
from services.recording_selection import select_recording


WANTED = {'title': 'Creep (feat. Radiohead) [Very 2021 Rmx]',
          'artist': 'Thom Yorke', 'duration': 542}
CANDIDATE = {'title': 'Creep (Very 2021 Thom Yorke Rmx)',
             'artist': 'Radiohead, Thom Yorke', 'duration': 543,
             'source': 'youtube', 'source_id': 'wYRAGR91CHQ'}


def test_named_remix_matches_when_catalogue_adds_credited_remixer():
    assert select_recording(WANTED, [CANDIDATE]) is CANDIDATE
    assert same_recording(CANDIDATE, WANTED)


@pytest.mark.parametrize('changes', [
    {'title': 'Creep (Other 2021 Thom Yorke Rmx)'},
    {'title': 'Creep (Very 2020 Thom Yorke Rmx)'},
    {'title': 'Creep (Very 2021 Another DJ Rmx)'},
    {'title': 'Creep (Very 2021 Rmx)', 'artist': 'Another Band'},
    {'duration': 238},
])
def test_remixer_credit_does_not_accept_other_recording(changes):
    assert not same_recording(WANTED, dict(CANDIDATE, **changes))


def test_generic_remix_is_not_enough_evidence_of_named_remixer():
    assert not same_recording({'title': 'Song (Remix)', 'artist': 'Artist'},
                              {'title': 'Song (Artist Remix)', 'artist': 'Artist'})
