from datetime import datetime, timezone
import json

import pytest

from core.user_errors import describe_error
from services.listening_comparison import listening_comparison


def add_play(db, title, artist, when, seconds):
    identifier = db.add_track(title, artist=artist)
    db.conn.execute('INSERT INTO history(track_id, played_at, duration_listened, listening_measured) VALUES (?, ?, ?, 1)',
                    (identifier, when, seconds))
    db.conn.commit()


def test_comparison_uses_equal_nonoverlapping_windows_and_real_listening(tmp_db):
    add_play(tmp_db, 'Previous', 'Old artist', '2026-10-05 12:00:00', 120)
    add_play(tmp_db, 'Current', 'New artist', '2026-10-12 22:00:00', 180)
    add_play(tmp_db, 'Boundary', 'Old artist', '2026-10-08 12:00:00', 60)
    add_play(tmp_db, 'Silent', 'Unused artist', '2026-10-13 12:00:00', 0)
    result = listening_comparison(tmp_db, 'week', 180, now=datetime(2026, 10, 15, 12, tzinfo=timezone.utc))
    assert result['previous']['plays'] == 1
    assert result['current']['plays'] == 2
    assert result['current']['seconds'] == 240
    assert result['delta']['seconds']['percent'] == 100
    assert result['new_artists'] == [{'artist': 'New artist', 'seconds': 180}]
    assert result['current']['daily'][-1]['day'] == '2026-10-13'
    json.dumps(result, allow_nan=False)


def test_empty_comparison_does_not_fabricate_growth(tmp_db):
    result = listening_comparison(tmp_db)
    assert result['current']['seconds'] == 0
    assert result['delta']['seconds'] == {'absolute': 0, 'percent': None}
    assert result['new_artists'] == []


def test_returning_artist_has_old_listening_but_no_previous_window(tmp_db):
    add_play(tmp_db, 'Old favorite', 'Returning artist', '2026-09-10 12:00:00', 120)
    add_play(tmp_db, 'Old favorite', 'Returning artist', '2026-10-12 12:00:00', 150)
    result = listening_comparison(tmp_db, now=datetime(2026, 10, 15, 12, tzinfo=timezone.utc))
    assert result['returning_artists'] == [{'artist':'Returning artist', 'seconds':150}]
    assert result['new_artists'] == []


@pytest.mark.parametrize('period,offset', [('unknown', 180), ('week', 900)])
def test_comparison_rejects_invalid_filters(tmp_db, period, offset):
    with pytest.raises(ValueError):
        listening_comparison(tmp_db, period, offset)


@pytest.mark.parametrize('error,code,action', [
    (OSError(28, 'disk full'), 'disk_full', 'storage'),
    (FileNotFoundError('path'), 'file_missing', 'library'),
    (TimeoutError('timed out'), 'network', 'retry'),
    ('offline', 'network', 'retry'),
    ('403 unavailable', 'unavailable', 'search'),
])
def test_errors_explain_recovery_action_without_exposing_paths(error, code, action):
    result = describe_error(error)
    assert result['code'] == code
    assert result['action'] == action
    json.dumps(result)
