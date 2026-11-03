"""Deterministic, provider-free AppApi behavior for UI benchmark scenarios.

These patches are installed only inside the throwaway benchmark subprocess.
They preserve bridge event names and shapes while avoiding network providers.
"""

from __future__ import annotations

import wave
from pathlib import Path
from typing import Any


def _tracks(api, limit: int = 50) -> list[dict[str, Any]]:
    db = api._core.db
    page = getattr(db, "get_library_page", None)
    if callable(page):
        return [dict(row) for row in page(limit=limit, offset=0)]
    return [dict(row) for row in (db.get_all_tracks() or [])[:limit]]


def _pending(request_id=None):
    payload = {"status": "pending"}
    if request_id is not None:
        payload["request_id"] = str(request_id)
    return payload


def _emit_rows(api, event: str, rows: list[dict], request_id=None):
    payload: Any = rows
    if request_id is not None:
        key = "tracks"
        payload = {"request_id": str(request_id), key: rows}
    api._emit(event, payload)


def _write_silent_wav(path: Path, seconds: int = 2) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(22050)
        stream.writeframes(b"\0\0" * (22050 * seconds))


def install_benchmark_api_stubs(api_type, profile_root: str | Path) -> None:
    """Patch provider-facing bridge methods for one isolated benchmark child."""
    root = Path(profile_root).resolve()

    def search(self, query: str, source: str = "all", result_type=None, request_id=None):
        clean_query = (query or "").strip()
        rows = _tracks(self, 50) if clean_query else []
        self._emit("search_results", {
            "query": clean_query, "source": "fixture", "type": result_type,
            "tracks": rows, "offline": False, "request_id": request_id,
        })
        self._emit("search_completed", {"query": clean_query, "source": source, "request_id": request_id})
        return {"query": clean_query, "tracks": rows}

    def get_feed(self, max_results: int = 20, request_id=None):
        rows = _tracks(self, max_results)
        _emit_rows(self, "feed_ready", rows, request_id)
        return _pending(request_id)

    def get_authentic_home_feed(self, limit: int = 20):
        rows = _tracks(self, limit)
        self._emit("authentic_home_ready", {
            "sections": [{"title": "Benchmark fixture", "items": rows}]
        })
        return {"status": "pending"}

    def get_popular_tracks(self, region: str = "US", request_id=None):
        _emit_rows(self, "popular_results", _tracks(self, 10), request_id)
        return _pending(request_id)

    def get_home_releases(self, max_results: int = 10, request_id=None):
        _emit_rows(self, "releases_ready", _tracks(self, max_results), request_id)
        return _pending(request_id)

    def get_home_mixes(self, max_results: int = 10, request_id=None):
        _emit_rows(self, "mixes_ready", _tracks(self, max_results), request_id)
        return _pending(request_id)

    def download_track(self, track_data: dict):
        if not isinstance(track_data, dict):
            return False
        track_id = track_data.get("id") or track_data.get("track_id")
        track_id_text = str(track_id) if track_id is not None else ""
        row = self._core.db.get_track(int(track_id_text)) if track_id_text.isdecimal() else None
        if not row:
            row = next((candidate for candidate in _tracks(self, 1000)
                        if candidate.get("source") != "local"), None)
        if not row:
            return False
        dest = root / ".nedotify" / "bench-downloads" / f"track-{row['id']}.wav"
        _write_silent_wav(dest)
        self._core.db.mark_track_downloaded(int(row["id"]), str(dest))
        self._emit("download_progress", {
            "track_id": row["id"], "status": "completed", "progress": 100,
            "file_path": str(dest), "benchmark_fixture": True,
        })
        self._emit("download_complete", {"track_id": row["id"], "benchmark_fixture": True})
        return True

    api_type.search = search
    api_type.get_feed = get_feed
    api_type.get_authentic_home_feed = get_authentic_home_feed
    api_type.get_popular_tracks = get_popular_tracks
    api_type.get_home_releases = get_home_releases
    api_type.get_home_mixes = get_home_mixes
    api_type.download_track = download_track
