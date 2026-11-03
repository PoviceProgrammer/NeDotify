"""
NeDotify - Audio Fingerprint & Duplicate Detection Service
Scans local audio tracks, computes exact SHA-256 file hashes,
and identifies duplicate song entries in the library.
"""

import hashlib
import logging
import os
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)

# Confidence reported for duplicate groups: a full-content hash is exact, while a
# sampled hash (head/middle/tail only) can only suggest a duplicate.
FULL_HASH_MATCH_CONFIDENCE = 100.0
SAMPLED_MATCH_CONFIDENCE = 90.0


class AudioFingerprintService:
    """Service for computing exact file hashes and scanning for duplicate audio files."""

    def __init__(self):
        pass

    def compute_file_fingerprint(self, filepath: str, sample_bytes: int = 65536) -> Optional[Dict[str, Any]]:
        """Compute fast, robust audio fingerprint from file content, size, and header signature."""
        if not filepath or not os.path.exists(filepath):
            return None

        try:
            file_size = os.path.getsize(filepath)
            digest = hashlib.sha256()
            with open(filepath, "rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
            fingerprint_hash = digest.hexdigest()
            return {
                "hash": fingerprint_hash,
                "file_size": file_size,
                "full_hash": True,
                "signature": f"{fingerprint_hash}_{file_size}"
            }
        except Exception as e:
            logger.error(f"Error computing audio fingerprint for {filepath}: {e}")
            return None

    def find_duplicates(self, db_manager) -> List[Dict[str, Any]]:
        """
        Scan all local tracks in database and find groups of duplicates.
        Returns a list of duplicate groups with confidence percentages.
        """
        if not db_manager:
            return []

        all_tracks = db_manager.get_all_tracks()
        if not all_tracks:
            return []

        fingerprint_map: Dict[str, List[Dict[str, Any]]] = {}

        for track in all_tracks:
            file_path = track.get("file_path")
            if not file_path or not os.path.exists(file_path):
                continue

            fp = self.compute_file_fingerprint(file_path)
            if not fp:
                continue

            sig = fp["signature"]
            if sig not in fingerprint_map:
                fingerprint_map[sig] = []
            
            track_entry = dict(track)
            track_entry["fingerprint"] = fp["hash"]
            track_entry["file_size_bytes"] = fp["file_size"]
            track_entry["full_hash"] = fp["full_hash"]
            fingerprint_map[sig].append(track_entry)

        # Filter only groups with 2 or more tracks
        duplicate_groups = []
        group_idx = 1
        for sig, tracks_list in fingerprint_map.items():
            if len(tracks_list) > 1:
                duplicate_groups.append({
                    "group_id": f"dup_{group_idx}",
                    "signature": sig,
                    "match_confidence": (
                        FULL_HASH_MATCH_CONFIDENCE if all(t.get("full_hash") for t in tracks_list)
                        else SAMPLED_MATCH_CONFIDENCE
                    ),
                    "count": len(tracks_list),
                    "tracks": tracks_list
                })
                group_idx += 1

        return duplicate_groups

    @staticmethod
    def _same_path(first: str, second: str) -> bool:
        return os.path.normcase(os.path.realpath(first)) == os.path.normcase(os.path.realpath(second))

    def delete_duplicate_track(
        self, db_manager, duplicate_id: int, delete_file: bool = False,
        keeper_id: Optional[int] = None,
    ) -> bool:
        """Merge an exact-content duplicate into a keeper, optionally removing its file.

        A row is never deleted on its own: both rows must still exist, have
        readable files, and have the same full SHA-256 before the database
        merge is attempted. The keeper's file is preserved even when both rows
        point to the same path.
        """
        if not db_manager:
            return False
        if (not isinstance(duplicate_id, int) or isinstance(duplicate_id, bool)
                or duplicate_id <= 0):
            return False

        try:
            duplicate = db_manager.get_track(duplicate_id)
            if not duplicate:
                return False
            if keeper_id is None:
                # Preserve the legacy one-id API safely: resolve a keeper only
                # from a verified full-content match in the current library.
                duplicate_path = duplicate.get("file_path")
                duplicate_fp = self.compute_file_fingerprint(duplicate_path)
                if not duplicate_fp or not duplicate_fp.get("full_hash"):
                    return False
                for candidate in db_manager.get_all_tracks() or []:
                    candidate_id = candidate.get("id")
                    if candidate_id == duplicate_id:
                        continue
                    candidate_fp = self.compute_file_fingerprint(candidate.get("file_path"))
                    if (candidate_fp and candidate_fp.get("full_hash")
                            and candidate_fp.get("hash") == duplicate_fp.get("hash")):
                        keeper_id = candidate_id
                        break
            if (not isinstance(keeper_id, int) or isinstance(keeper_id, bool)
                    or keeper_id <= 0 or keeper_id == duplicate_id):
                return False
            keeper = db_manager.get_track(keeper_id)
            if not duplicate or not keeper:
                return False
            duplicate_path = duplicate.get("file_path")
            keeper_path = keeper.get("file_path")
            if not duplicate_path or not keeper_path:
                return False
            duplicate_fp = self.compute_file_fingerprint(duplicate_path)
            keeper_fp = self.compute_file_fingerprint(keeper_path)
            if (not duplicate_fp or not keeper_fp
                    or not duplicate_fp.get("full_hash") or not keeper_fp.get("full_hash")
                    or duplicate_fp.get("hash") != keeper_fp.get("hash")):
                return False

            merge = getattr(db_manager, "merge_duplicate_track", None)
            if not callable(merge) or not merge(duplicate_id, keeper_id):
                return False

            if delete_file and not self._same_path(duplicate_path, keeper_path):
                try:
                    os.remove(duplicate_path)
                except FileNotFoundError:
                    pass
                except OSError as exc:
                    # The library merge succeeded and the keeper remains safe;
                    # the API can report this leftover file as a partial result.
                    logger.warning("Merged duplicate %s but could not remove %s: %s",
                                   duplicate_id, duplicate_path, exc)
            return True
        except Exception as e:
            logger.error("Failed to merge duplicate track %s into %s: %s",
                         duplicate_id, keeper_id, e)
            return False
