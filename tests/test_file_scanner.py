"""File-scanner identity, streaming, cancellation, and shutdown contracts."""

import os
import threading

import utils.file_scanner as scanner_module
from utils.file_scanner import FileScanner


def test_importing_same_metadata_from_different_files_keeps_both_paths(tmp_db, tmp_path, monkeypatch):
    first = tmp_path / "first.mp3"
    second = tmp_path / "second.mp3"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    monkeypatch.setattr(scanner_module, "parse_tags", lambda path: {
        "title": "Same Song", "artist": "Same Artist", "album": "Album",
        "duration": 120, "bitrate": 0, "format": "MP3", "genre": None,
        "year": None, "cover_data": None, "cover_mime": None,
    })

    scanner = FileScanner(tmp_db)
    imported = scanner.scan_files([str(first), str(second), str(first)])

    assert len(imported) == 2
    assert imported[0]["id"] != imported[1]["id"]
    assert tmp_db.get_track_by_path(str(first))["id"] == imported[0]["id"]
    assert tmp_db.get_track_by_path(str(second))["id"] == imported[1]["id"]
    assert tmp_db.get_all_tracks(source="local") and len(tmp_db.get_all_tracks(source="local")) == 2


def test_folder_scan_streams_paths_and_reports_unknown_total(tmp_db, tmp_path, monkeypatch):
    first = str(tmp_path / "one.mp3")
    second = str(tmp_path / "sub" / "two.flac")
    enumerated = []
    imported = []
    completed = threading.Event()
    scanner = FileScanner(tmp_db)

    def walk(_folder):
        yield str(tmp_path), [], ["one.mp3"]
        # The first path must already have been consumed before requesting the
        # next directory batch; a full-tree materialization fails this check.
        assert imported == [first]
        yield str(tmp_path / "sub"), [], ["two.flac"]

    monkeypatch.setattr(scanner_module.os, "walk", walk)
    def fake_import(path):
        imported.append(path)
        return {"id": len(imported), "file_path": path}
    scanner._import_file = fake_import
    scanner.on_progress(lambda current, total, path: enumerated.append((current, total, path)))
    scanner.on_complete(lambda _tracks: completed.set())

    assert scanner.scan_folder(str(tmp_path)) is True
    assert completed.wait(3)
    assert enumerated == [(1, None, first), (2, None, second)]
    assert tmp_db.get_scan_folders()[0]["folder_path"] == os.path.abspath(tmp_path)


def test_scan_folder_reports_invalid_and_concurrent_requests(tmp_db, tmp_path):
    scanner = FileScanner(tmp_db)
    assert scanner.scan_folder(str(tmp_path / "missing")) is False

    entered = threading.Event()
    release = threading.Event()
    completed = threading.Event()
    scanner._iter_audio_files = lambda *_args: iter([str(tmp_path / "blocked.mp3")])
    def blocked_import(path):
        entered.set()
        assert release.wait(3)
        return {"file_path": path}
    scanner._import_file = blocked_import
    scanner.on_complete(lambda _tracks: completed.set())

    assert scanner.scan_folder(str(tmp_path)) is True
    assert entered.wait(2)
    assert scanner.scan_folder(str(tmp_path)) is False
    release.set()
    assert completed.wait(2)
    scanner._scan_thread.join(2)
    assert scanner._scan_thread is not None and not scanner._scan_thread.is_alive()


def test_stop_cancels_joins_worker_and_prevents_restart(tmp_db, tmp_path):
    scanner = FileScanner(tmp_db)
    entered = threading.Event()
    release = threading.Event()
    completed = []
    published = []
    scanner._iter_audio_files = lambda *_args: iter([str(tmp_path / "blocked.mp3")])
    def blocked_import(path):
        entered.set()
        assert release.wait(3)
        return {"file_path": path}
    scanner._import_file = blocked_import
    scanner.on_complete(lambda tracks: completed.append(tracks))
    scanner.on_file_found(lambda track: published.append(("track", track)))
    scanner.on_progress(lambda *args: published.append(("progress", args)))

    assert scanner.scan_folder(str(tmp_path)) is True
    assert entered.wait(2)
    release_thread = threading.Thread(target=lambda: (threading.Event().wait(.05), release.set()))
    release_thread.start()
    assert scanner.stop(timeout=2) is True
    release_thread.join(2)
    assert scanner._scan_thread is not None and not scanner._scan_thread.is_alive()
    assert completed == [], "a cancelled scan must not publish a completed result"
    assert published == [], "a cancelled in-flight import must not publish stale callbacks"
    assert tmp_db.get_scan_folders() == [], "a cancelled scan must not be recorded as complete"
    assert scanner.scan_folder(str(tmp_path)) is False


def test_cancel_timeout_reports_worker_still_running(tmp_db, tmp_path):
    scanner = FileScanner(tmp_db)
    entered = threading.Event()
    release = threading.Event()
    scanner._iter_audio_files = lambda *_args: iter([str(tmp_path / "blocked.mp3")])
    def blocked_import(path):
        entered.set()
        release.wait(3)
        return {"file_path": path}
    scanner._import_file = blocked_import

    assert scanner.scan_folder(str(tmp_path)) is True
    assert entered.wait(2)
    assert scanner.cancel_scan(timeout=.01) is False
    assert scanner.scan_folder(str(tmp_path)) is False, "old worker must not overlap a new generation"
    release.set()
    scanner._scan_thread.join(2)
    assert not scanner._scan_thread.is_alive()

