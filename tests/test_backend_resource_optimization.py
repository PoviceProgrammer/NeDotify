"""Operation budgets and legacy compatibility for library background work."""
import os
from types import SimpleNamespace

from core import offline
from services.lufs_scanner import LufsScannerService


def local_track(db, path, title='Saved', **kwargs):
    path.write_bytes(b'audio' * 2048)
    return db.add_track(title, artist='Artist', file_path=str(path), **kwargs)


def test_summary_uses_compact_rows_and_preserves_legacy_keys_and_exists(api, tmp_db, tmp_path, monkeypatch):
    identifier = local_track(tmp_db, tmp_path / 'saved.mp3', source_id='provider-key',
                             is_favorite=1, is_downloaded=1)
    # Existing downloads deliberately use exists, not the offline audio test.
    directory = tmp_path / 'directory'
    directory.mkdir()
    tmp_db.add_track('Directory', file_path=str(directory), is_downloaded=1)
    tmp_db.add_track('Missing', file_path=str(tmp_path / 'missing.mp3'), is_downloaded=1)
    monkeypatch.setattr(tmp_db, 'get_favorite_tracks', lambda: (_ for _ in ()).throw(AssertionError('full favorites')))
    monkeypatch.setattr(tmp_db, 'get_downloaded_tracks', lambda: (_ for _ in ()).throw(AssertionError('full downloads')))
    result = api.get_library_summary()
    assert result == {'favorite_count': 1, 'favorite_ids': sorted([str(identifier), 'provider-key']), 'downloaded_count': 2}


def test_offline_refresh_handles_delete_cache_change_and_content_expiry(tmp_db, tmp_path, monkeypatch):
    first = local_track(tmp_db, tmp_path / 'first.mp3')
    remote = tmp_db.add_track('Remote', source='youtube', source_id='remote')
    cached = tmp_path / 'cache.mp3'
    cached.write_bytes(b'x' * 5000)
    tmp_db.cache_stream('youtube', 'remote', 'https://example.com/audio')
    tmp_db.set_cached_file('youtube', 'remote', str(cached))
    assert set(offline.offline_library_ids(tmp_db)) == {first, remote}
    (tmp_path / 'first.mp3').unlink()
    assert [t['id'] for t in offline.offline_library_page(tmp_db, 5)[0]] == [remote]
    # In-place truncation is reconciled lazily on page query / playback without disk storms.
    cached.write_bytes(b'x')
    assert offline.offline_library_page(tmp_db, 5)[0] == []
    assert offline.offline_library_ids(tmp_db) == []
    replacement = tmp_path / 'replacement.mp3'
    replacement.write_bytes(b'x' * 5000)
    tmp_db.set_cached_file('youtube', 'remote', str(replacement))
    assert offline.offline_library_ids(tmp_db) == [remote]


def test_offline_disk_checks_never_hold_database_write_lock(tmp_db, tmp_path, monkeypatch):
    local_track(tmp_db, tmp_path / 'saved.mp3')
    original = offline._local_file
    def check(*args, **kwargs):
        assert not tmp_db._write_lock._is_owned()
        return original(*args, **kwargs)
    monkeypatch.setattr(offline, '_local_file', check)
    assert len(offline.offline_library_page(tmp_db, 10)[0]) == 1


def test_fts_ignores_nonsearch_writes_and_noop_metadata(tmp_db):
    identifier = tmp_db.add_track('Original', artist='Artist')
    for statement in ('UPDATE tracks SET play_count=play_count+1 WHERE id=?',
                      'UPDATE tracks SET lufs=-16,loudness_lufs=-16 WHERE id=?',
                      'UPDATE tracks SET is_favorite=1 WHERE id=?',
                      'UPDATE tracks SET title=title,artist=artist WHERE id=?'):
        before = tmp_db.conn.total_changes
        with tmp_db.conn:
            tmp_db.conn.execute(statement, (identifier,))
        assert tmp_db.conn.total_changes - before == 1
    with tmp_db.conn:
        tmp_db.conn.execute('UPDATE tracks SET title=? WHERE id=?', ('Replacement', identifier))
    assert [t['id'] for t in tmp_db.search_tracks('Replacement')] == [identifier]
    assert not tmp_db.search_tracks('Original')


def test_fts_trigger_upgrade_and_one_time_legacy_backfills(tmp_db):
    identifier = tmp_db.add_track('Legacy', duration=120)
    with tmp_db.conn:
        tmp_db.conn.execute('DELETE FROM schema_migrations WHERE version IN (?,?)',
                            ('history_duration_backfill_v1', 'lufs_columns_backfill_v1'))
        tmp_db.conn.execute('INSERT INTO history(track_id,duration_listened,listening_measured) VALUES (?,0,0)', (identifier,))
        tmp_db.conn.execute('INSERT INTO history(track_id,duration_listened,listening_measured) VALUES (?,0,1)', (identifier,))
        tmp_db.conn.execute('UPDATE tracks SET lufs=-13,loudness_lufs=NULL WHERE id=?', (identifier,))
        tmp_db.conn.execute('DROP TRIGGER tracks_au')
        tmp_db.conn.execute('''CREATE TRIGGER tracks_au AFTER UPDATE ON tracks BEGIN
            INSERT INTO tracks_fts(tracks_fts,rowid,title,artist,album,genre)
            VALUES('delete',old.id,old.title,old.artist,old.album,old.genre);
            INSERT INTO tracks_fts(rowid,title,artist,album,genre)
            VALUES(new.id,new.title,new.artist,new.album,new.genre); END''')
    tmp_db._init_database()
    assert [r[0] for r in tmp_db.conn.execute('SELECT duration_listened FROM history ORDER BY id')] == [120, 0]
    assert tmp_db.get_track(identifier)['loudness_lufs'] == -13
    statements = []
    tmp_db.conn.set_trace_callback(statements.append)
    try:
        tmp_db._init_database()
    finally:
        tmp_db.conn.set_trace_callback(None)
    assert not any('UPDATE history' in q or 'SET loudness_lufs = lufs WHERE' in q or 'SET lufs = loudness_lufs WHERE' in q for q in statements)
    sql = tmp_db.conn.execute("SELECT sql FROM sqlite_master WHERE name='tracks_au'").fetchone()[0]
    assert 'AFTER UPDATE OF' in sql


def scanner_for(db, monkeypatch):
    scanner = LufsScannerService(SimpleNamespace(db=db))
    monkeypatch.setattr(scanner._stop, 'wait', lambda duration: scanner._stop.is_set())
    return scanner


def test_lufs_idle_poll_has_constant_database_work_and_zero_file_checks(tmp_db, monkeypatch):
    with tmp_db.conn:
        tmp_db.conn.executemany('INSERT INTO tracks(title,file_path) VALUES (?,?)',
                               ((str(i), f'{i}.mp3') for i in range(2000)))
        tmp_db.conn.execute('DELETE FROM lufs_pending')
    scanner = scanner_for(tmp_db, monkeypatch)
    monkeypatch.setattr(scanner, '_signature', lambda path: (_ for _ in ()).throw(AssertionError('idle stat')))
    operations = []
    tmp_db.conn.set_progress_handler(lambda: (operations.append(1), 0)[1], 1)
    try:
        assert scanner._process_pending_batch() == 0
        assert len(operations) < 100
    finally:
        tmp_db.conn.set_progress_handler(None, 0)
        scanner.stop()


def test_lufs_new_and_same_path_rewrite_are_measured_once(tmp_db, tmp_path, monkeypatch):
    path = tmp_path / 'saved.mp3'
    identifier = local_track(tmp_db, path)
    scanner = scanner_for(tmp_db, monkeypatch)
    calls = []
    monkeypatch.setattr(scanner, '_analyze_background', lambda p: (calls.append(p), (-14.5, .8, None))[1])
    try:
        assert scanner._process_pending_batch() == 1
        assert scanner._process_pending_batch() == 0
        assert tmp_db.get_track(identifier)['lufs'] == -14.5
        stamp = path.stat().st_mtime_ns
        path.write_bytes(b'new audio' * 2000)
        os.utime(path, ns=(stamp + 10_000_000, stamp + 10_000_000))
        scanner.enqueue_path(str(path))
        scanner._process_pending_batch()
        scanner._reconcile_batch(0)
        assert calls == [str(path), str(path)]
    finally:
        scanner.stop()


def test_lufs_cancel_and_rewrite_during_analysis_keep_pending_work(tmp_db, tmp_path, monkeypatch):
    path = tmp_path / 'saved.mp3'
    identifier = local_track(tmp_db, path)
    scanner = scanner_for(tmp_db, monkeypatch)
    def rewrite(p):
        path.write_bytes(b'rewritten content')
        return -12, .9, None
    monkeypatch.setattr(scanner, '_analyze_background', rewrite)
    try:
        scanner._process_pending_batch()
        assert tmp_db.get_track(identifier)['lufs'] is None
        assert tmp_db.conn.execute('SELECT COUNT(*) FROM lufs_pending').fetchone()[0] == 1
        def cancel(p):
            scanner._stop.set()
            return -12, .9, None
        monkeypatch.setattr(scanner, '_analyze_background', cancel)
        scanner._process_pending_batch()
        assert tmp_db.get_track(identifier)['lufs'] is None
        assert tmp_db.conn.execute('SELECT COUNT(*) FROM lufs_pending').fetchone()[0] == 1
    finally:
        scanner.stop()


def test_lufs_reconciliation_detects_rewrites_outside_watched_roots(tmp_db, tmp_path, monkeypatch):
    path = tmp_path / 'unwatched.mp3'
    identifier = local_track(tmp_db, path)
    scanner = scanner_for(tmp_db, monkeypatch)
    calls = []
    monkeypatch.setattr(scanner, '_analyze_background', lambda p: (calls.append(p), (-14, .8, None))[1])
    try:
        scanner._process_pending_batch()
        path.write_bytes(b'new contents')
        assert scanner._process_pending_batch() == 0
        scanner._reconcile_batch(0)
        assert calls == [str(path), str(path)]
        assert tmp_db.get_track(identifier)['lufs'] == -14
    finally:
        scanner.stop()


def test_lufs_does_not_publish_old_path_measurement_over_replaced_file(tmp_db, tmp_path, monkeypatch):
    original = tmp_path / 'original.mp3'
    replacement = tmp_path / 'replacement.mp3'
    replacement.write_bytes(b'replacement audio')
    identifier = local_track(tmp_db, original)
    scanner = scanner_for(tmp_db, monkeypatch)
    def change_path(path):
        with tmp_db._write_lock, tmp_db.conn:
            tmp_db.conn.execute('UPDATE tracks SET file_path=? WHERE id=?', (str(replacement), identifier))
        return -11, .9, None
    monkeypatch.setattr(scanner, '_analyze_background', change_path)
    try:
        scanner._process_pending_batch()
        track = tmp_db.get_track(identifier)
        assert track['file_path'] == str(replacement) and track['lufs'] is None
        assert tmp_db.conn.execute('SELECT COUNT(*) FROM lufs_pending').fetchone()[0] == 1
    finally:
        scanner.stop()


def test_watchdog_queues_lufs_for_existing_file_without_library_event(tmp_db, tmp_path):
    from services.watchdog_service import WatchdogService
    path = tmp_path / 'existing.mp3'
    local_track(tmp_db, path)
    queued = []
    core = SimpleNamespace(db=tmp_db, lufs_scanner=SimpleNamespace(enqueue_path=queued.append),
                           scanner=SimpleNamespace(_import_file=lambda p: None))
    WatchdogService(core)._on_new_file(str(path))
    assert queued == [str(path)]


def test_playlist_cover_limit_is_bounded_and_default_still_returns_all(api, tmp_db):
    playlist = tmp_db.create_playlist('Samples')
    identifiers = [tmp_db.add_track(f'Sample {i}', artist='Artist') for i in range(8)]
    for identifier in identifiers:
        tmp_db.add_to_playlist(playlist, identifier)
    assert len(api.get_playlist_tracks(playlist)['tracks']) == 8
    assert len(api.get_playlist_tracks(playlist, 'local', 4)['tracks']) == 4
