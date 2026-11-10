"""
Tests for track_lyrics_overrides in DatabaseManager.
"""
import os
import tempfile
import pytest

from core.database import DatabaseManager


@pytest.fixture
def temp_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    db = DatabaseManager(path)
    yield db
    try:
        db.close()
    except Exception:
        pass
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass


def test_lyrics_override_crud(temp_db):
    identity = "youtube:dQw4w9WgXcQ"
    # 1. Set override
    success = temp_db.set_track_lyrics_override(
        identity_key=identity,
        override_type="chosen_version",
        source_name="LRCLIB",
        plain_lyrics="Never gonna give you up\nNever gonna let you down",
        synced_lyrics="[00:18.00]Never gonna give you up\n[00:20.50]Never gonna let you down",
        sync_type="line",
        source_id="12345",
        track_id=1,
        offset_ms=200,
    )
    assert success is True

    # 2. Get override by identity_key
    row = temp_db.get_track_lyrics_override(identity_key=identity)
    assert row is not None
    assert row["source_name"] == "LRCLIB"
    assert row["override_type"] == "chosen_version"
    assert "Never gonna give you up" in row["plain_lyrics"]
    assert row["offset_ms"] == 200

    # 3. Get override by track_id
    row_by_id = temp_db.get_track_lyrics_override(track_id=1)
    assert row_by_id is not None
    assert row_by_id["identity_key"] == identity

    # 4. Update override
    temp_db.set_track_lyrics_override(
        identity_key=identity,
        override_type="custom_user",
        source_name="Пользовательский",
        plain_lyrics="Custom lyrics edited by user",
        synced_lyrics=None,
        sync_type="plain",
        track_id=1,
    )
    updated = temp_db.get_track_lyrics_override(identity_key=identity)
    assert updated["override_type"] == "custom_user"
    assert updated["plain_lyrics"] == "Custom lyrics edited by user"
    assert updated["synced_lyrics"] is None

    # 5. Delete override
    deleted = temp_db.delete_track_lyrics_override(identity_key=identity)
    assert deleted is True
    assert temp_db.get_track_lyrics_override(identity_key=identity) is None
