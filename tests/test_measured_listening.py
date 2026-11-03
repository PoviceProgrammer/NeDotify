"""Actual audible time drives taste and recommendation outcomes."""
import pytest
from core import listening
from services.taste_profile import UserTasteProfile


@pytest.fixture
def clock(monkeypatch):
    value = [1000.0]
    monkeypatch.setattr(listening.time, 'monotonic', lambda: value[0])
    return value


def current(api, tmp_db, tmp_path, title='Track', duration=100, origin='feed'):
    tid = tmp_db.add_track(title=title, artist='Artist', source='youtube',
                          source_id=(title + '___________')[:11], duration=duration)
    track = tmp_db.get_track(tid)
    track['recommendation_origin'] = origin
    # Keep the engine queue active and the stream ready so this helper exercises
    # listening accounting without starting a provider resolution task.
    ready_file = tmp_path / f'{tid}.audio'
    ready_file.write_bytes(b'audio fixture')
    track['file_path'] = str(ready_file)
    api._core.engine.queue.set_tracks([track], 0)
    api._on_track_changed(track)
    return api._current_track['listening_session'], tid


def row(tmp_db, tid):
    return dict(tmp_db.conn.execute('SELECT * FROM history WHERE track_id=? ORDER BY id DESC LIMIT 1', (tid,)).fetchone())


def test_start_pause_buffer_seek_resume_and_heartbeat_measure_real_time(api, tmp_db, clock, tmp_path):
    token, tid = current(api, tmp_db, tmp_path)
    assert tmp_db.conn.execute('SELECT COUNT(*) FROM history').fetchone()[0] == 0
    api.report_state('playing', listening_session=token)
    assert row(tmp_db, tid)['duration_listened'] == 0
    clock[0] += 3
    api.report_state('paused', listening_session=token)
    clock[0] += 100
    api.report_state('playing', listening_session=token)
    clock[0] += 2
    api.report_listening_state(token, False)  # waiting or seeking
    clock[0] += 60
    api.report_position(99000, 100000, listening_session=token)
    assert row(tmp_db, tid)['duration_listened'] == 5
    api.report_listening_state(token, True)
    clock[0] += 4
    api.report_position(10000, 100000, listening_session=token)
    assert row(tmp_db, tid)['duration_listened'] == 9
    assert tmp_db.get_track(tid)['play_count'] == 1
    assert row(tmp_db, tid)['listening_measured'] == 1


def test_playback_rate_transition_charges_each_interval_at_its_actual_rate(api, tmp_db, clock, tmp_path):
    token, tid = current(api, tmp_db, tmp_path)
    api.report_listening_state(token, True, playback_rate=1)
    clock[0] += 2
    api.report_listening_state(token, True, playback_rate=2)
    assert row(tmp_db, tid)['media_listened'] == 2
    clock[0] += 3
    api.report_listening_state(token, True, playback_rate=.5)
    assert row(tmp_db, tid)['media_listened'] == 8
    clock[0] += 4
    api.report_listening_state(token, False, playback_rate=.5)
    measured = row(tmp_db, tid)
    assert measured['media_listened'] == 10
    assert measured['duration_listened'] == 9


def test_completion_requires_heard_duration_not_just_seek_to_end(api, tmp_db, clock, tmp_path):
    token, tid = current(api, tmp_db, tmp_path)
    api.report_state('playing', listening_session=token)
    clock[0] += 2
    api.report_listening_state(token, False, ended=True)
    assert row(tmp_db, tid)['completed'] == 0
    token, tid = current(api, tmp_db, tmp_path, title='Full')
    api.report_state('playing', listening_session=token)
    for _ in range(18):
        clock[0] += 5
        api.report_position(0, 100000, listening_session=token)
    api.report_listening_state(token, False, ended=True)
    assert row(tmp_db, tid)['completed'] == 1
    assert row(tmp_db, tid)['duration_listened'] == 90


def test_track_switch_stale_state_and_close_do_not_mix_history(api, tmp_db, clock, tmp_path):
    old, old_id = current(api, tmp_db, tmp_path, title='Old')
    api.report_state('playing', listening_session=old)
    clock[0] += 4
    new, new_id = current(api, tmp_db, tmp_path, title='New')
    api.report_state('playing', listening_session=new)
    clock[0] += 3
    assert api.report_state('paused', listening_session=old) is False
    api.flush_listening()
    api.flush_listening()
    assert row(tmp_db, old_id)['duration_listened'] == 4
    assert row(tmp_db, new_id)['duration_listened'] == 3
    assert api._last_reported_state == 'playing'


def test_re_resolved_same_track_keeps_one_listening_session(api, tmp_db, clock, tmp_path):
    token, tid = current(api, tmp_db, tmp_path)
    api.report_state('playing', listening_session=token)
    clock[0] += 3
    api._on_track_changed(dict(api._current_track, stream_url='https://cdn.example/new'))
    assert api._current_track['listening_session'] == token
    api.report_state('playing', listening_session=token)
    assert tmp_db.get_track(tid)['play_count'] == 1


def test_zero_measured_listen_and_short_skip_have_honest_profile_weights():
    assert UserTasteProfile._listening_weight({'listening_measured': 1, 'duration_listened': 0, 'duration': 180}) == 0
    assert UserTasteProfile._listening_weight({'listening_measured': 1, 'session_finished': 1, 'duration_listened': 3, 'duration': 180}) == .1
    assert UserTasteProfile._listening_weight({'completed': 1, 'duration_listened': 175, 'duration': 180}) == 2


def test_local_quality_statistics_show_measured_recommendation_outcomes(api, tmp_db, clock, tmp_path):
    token, tid = current(api, tmp_db, tmp_path, duration=180)
    api.report_state('playing', listening_session=token)
    clock[0] += 3
    api.report_state('paused', listening_session=token)
    assert tmp_db.get_recommendation_quality()['groups'][0]['skips'] == 0
    api.flush_listening()
    data = tmp_db.get_recommendation_quality()['groups']
    assert data[0]['context'] == 'feed'
    assert data[0]['starts'] == 1 and data[0]['skips'] == 1
    assert data[0]['listened_seconds'] == 3


def test_double_speed_completion_preserves_wall_time(api, tmp_db, clock, tmp_path):
    token, tid = current(api, tmp_db, tmp_path, duration=20)
    api.report_state('playing', listening_session=token)
    api.report_listening_state(token, True, duration_sec=20, playback_rate=2)
    clock[0] += 10
    api.report_listening_state(token, False, ended=True, duration_sec=20, playback_rate=2)
    measured = row(tmp_db, tid)
    assert measured['duration_listened'] == 10
    assert measured['media_listened'] == 20
    assert measured['completed'] == 1 and measured['session_finished'] == 1


def test_measured_zero_survives_database_restart_and_unknown_legacy_length_stays_zero(tmp_db):
    tid = tmp_db.add_track(title='Measured', artist='Artist', source='youtube', source_id='measured', duration=180)
    hid = tmp_db.begin_listening_session(tid, 'feed')
    unknown = tmp_db.add_track(title='Unknown', artist='Artist', source='youtube', source_id='unknown', duration=0)
    tmp_db.add_to_history(unknown)
    tmp_db._init_database()
    assert tmp_db.conn.execute('SELECT duration_listened FROM history WHERE id=?', (hid,)).fetchone()[0] == 0
    assert row(tmp_db, unknown)['duration_listened'] == 0
