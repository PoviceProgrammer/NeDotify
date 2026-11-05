from __future__ import annotations

from pathlib import Path

from services.audio_fingerprint_service import AudioFingerprintService


class FakeDb:
    def __init__(self, duplicate_path: Path, keeper_path: Path, merge_result=True):
        self.rows = {
            1: {"id": 1, "file_path": str(duplicate_path)},
            2: {"id": 2, "file_path": str(keeper_path)},
        }
        self.merges = []
        self.merge_result = merge_result

    def get_track(self, track_id):
        return self.rows.get(track_id)

    def get_all_tracks(self):
        return list(self.rows.values())

    def merge_duplicate_track(self, duplicate_id, keeper_id):
        self.merges.append((duplicate_id, keeper_id))
        if self.merge_result:
            self.rows.pop(duplicate_id, None)
        return self.merge_result


def test_duplicate_merge_requires_exact_full_file_match_and_keeps_files_on_mismatch(tmp_path):
    duplicate = tmp_path / "duplicate.mp3"
    keeper = tmp_path / "keeper.mp3"
    duplicate.write_bytes(b"audio one")
    keeper.write_bytes(b"different audio")
    db = FakeDb(duplicate, keeper)

    assert not AudioFingerprintService().delete_duplicate_track(db, 1, delete_file=True, keeper_id=2)
    assert db.merges == []
    assert duplicate.exists() and keeper.exists()


def test_exact_duplicate_merges_then_removes_only_duplicate_file(tmp_path):
    duplicate = tmp_path / "duplicate.mp3"
    keeper = tmp_path / "keeper.mp3"
    duplicate.write_bytes(b"same audio bytes")
    keeper.write_bytes(b"same audio bytes")
    db = FakeDb(duplicate, keeper)

    assert AudioFingerprintService().delete_duplicate_track(db, 1, delete_file=True, keeper_id=2)
    assert db.merges == [(1, 2)]
    assert not duplicate.exists()
    assert keeper.read_bytes() == b"same audio bytes"


def test_same_path_keeper_is_never_unlinked(tmp_path):
    shared = tmp_path / "shared.mp3"
    shared.write_bytes(b"one shared file")
    db = FakeDb(shared, shared)

    assert AudioFingerprintService().delete_duplicate_track(db, 1, delete_file=True, keeper_id=2)
    assert db.merges == [(1, 2)]
    assert shared.read_bytes() == b"one shared file"


def test_legacy_one_id_call_resolves_only_an_exact_hash_keeper(tmp_path):
    duplicate = tmp_path / "duplicate.mp3"
    keeper = tmp_path / "keeper.mp3"
    duplicate.write_bytes(b"identical")
    keeper.write_bytes(b"identical")
    db = FakeDb(duplicate, keeper)

    assert AudioFingerprintService().delete_duplicate_track(db, 1, delete_file=True)
    assert db.merges == [(1, 2)]
    assert not duplicate.exists()
    assert keeper.exists()


def test_failed_database_merge_does_not_remove_duplicate_file(tmp_path):
    duplicate = tmp_path / "duplicate.mp3"
    keeper = tmp_path / "keeper.mp3"
    duplicate.write_bytes(b"same")
    keeper.write_bytes(b"same")
    db = FakeDb(duplicate, keeper, merge_result=False)

    assert not AudioFingerprintService().delete_duplicate_track(db, 1, delete_file=True, keeper_id=2)
    assert duplicate.exists() and keeper.exists()


def test_invalid_or_identical_track_ids_are_rejected(tmp_path):
    track = tmp_path / "track.mp3"
    track.write_bytes(b"audio")
    db = FakeDb(track, track)
    service = AudioFingerprintService()

    assert not service.delete_duplicate_track(db, 1, delete_file=True, keeper_id=1)
    assert not service.delete_duplicate_track(db, True, delete_file=True, keeper_id=2)
    assert db.merges == []
