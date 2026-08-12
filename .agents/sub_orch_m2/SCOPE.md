# Scope: Milestone 2 — Track Downloading & DB Integrity

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 6 | Downloader Spotify Fallback | Implement YouTube fallback search in `core/downloader.py` for Spotify track downloads (`source == "spotify"`). | M2 | ORIGINAL_REQUEST §2, Survey |
| 7 | Dedicated Download Directory | Isolate downloaded tracks to dedicated directory `.cache/downloads/` and ensure `CacheManager.enforce_cache_limit` only cleans `streams_dir`. | M2 | ORIGINAL_REQUEST §2, Survey |
| 8 | Downloader UI Events & Error Handling | Fix UI events & error feedback: backend emits `track_downloaded` and `download_failed`; frontend `events.js` handles both events and updates offline track list & error toasts. | M2 | ORIGINAL_REQUEST §2, Survey |
| 9 | Database Downloaded Status Integrity | Database update integrity: set `is_downloaded = 1` and `file_path = ...`, but preserve original `source` provider (`youtube`/`soundcloud`/`spotify`) without changing to `'local'`. | M2 | ORIGINAL_REQUEST §2, Survey |
| 10 | Windows Path & Filename Sanitization | Implement Windows path & filename sanitization utility (`utils/path_utils.py`) handling Cyrillic Unicode characters and illegal Windows characters (`\ / : * ? " < > \|`). | M2 | ORIGINAL_REQUEST §2, Survey |
| 11 | Downloader Queue Status & Error Reporting | Queue status tracking & error logging resilience: update `download_queue` status to `'failed'`, log errors, prevent false `is_downloaded` flags. | M2 | ORIGINAL_REQUEST §2, Survey |

## Interface Contracts
### Downloader ↔ API Bridge ↔ Frontend UI
- Completion event: `track_downloaded` with `{"track_id": track_id, "file_path": file_path}`
- Failure event: `download_failed` with `{"track_id": track_id, "error": error_msg}`
- Database update: `UPDATE tracks SET is_downloaded = 1, file_path = ? WHERE id = ?` (preserving original `source`)
