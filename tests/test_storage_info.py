import tempfile
from pathlib import Path
from types import SimpleNamespace

from core.api import AppApi
from core.database import DatabaseManager


def test_get_storage_info_returns_expected_contract():
    with tempfile.TemporaryDirectory() as temp_dir:
        db = DatabaseManager(str(Path(temp_dir) / "storage-test.db"))
        cache = SimpleNamespace(cache_dir=str(Path(temp_dir) / "cache"))
        scanner = SimpleNamespace(_covers_dir=str(Path(temp_dir) / "covers"))
        core = SimpleNamespace(db=db, cache=cache, scanner=scanner)
        api = AppApi(core)

        try:
            info = api.get_storage_info()
            assert isinstance(info, dict)
            assert "total" in info
            assert "tracks" in info
            assert "covers" in info
            assert isinstance(info["tracks"], dict)
            assert isinstance(info["covers"], dict)
            assert "count" in info["tracks"]
            assert "size" in info["tracks"]
            assert "count" in info["covers"]
            assert "size" in info["covers"]
        finally:
            db.close()
