"""
NeDotify - Cache Manager
Manages cover art cache, stream URL cache, and metadata cache with LRU eviction.
"""

import os
import shutil
import time
import logging
import threading
import concurrent.futures
from typing import Optional, Dict, Any, List
from core.database import DatabaseManager


class CacheManager:
    """Manages local caching of covers, stream URLs, and audio streams with LRU quota management."""

    def __init__(self, db: DatabaseManager, settings=None):
        self.db = db
        self.settings = settings
        self._base_dir = os.path.join(os.path.expanduser("~"), ".nedotify")
        self._covers_dir = os.path.join(self._base_dir, "covers")
        self._streams_dir = os.path.join(self._base_dir, "streams")
        self._temp_dir = os.path.join(self._base_dir, "temp")

        # Ensure directories exist
        for d in [self._covers_dir, self._streams_dir, self._temp_dir]:
            os.makedirs(d, exist_ok=True)

        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)
        self._active_downloads = set()
        self._active_downloads_lock = threading.Lock()
        self.logger = logging.getLogger("CacheManager")

        # Cached size scanning (Decision 1: rescan <= 1 time per 60s unless forced)
        self._size_cache_lock = threading.Lock()
        self._cached_size_bytes = 0
        self._last_size_scan = 0.0

    @property
    def cache_dir(self) -> str:
        """Root of the on-disk cache (covers/, streams/, temp/ live inside it)."""
        return self._base_dir

    @property
    def covers_dir(self) -> str:
        return self._covers_dir

    @property
    def streams_dir(self) -> str:
        return self._streams_dir

    @property
    def temp_dir(self) -> str:
        return self._temp_dir

    def get_cache_size(self, force_rescan: bool = False) -> int:
        """Get total cache size in bytes (cached with 60s TTL)."""
        now = time.time()
        with self._size_cache_lock:
            if not force_rescan and (now - self._last_size_scan < 60.0):
                return self._cached_size_bytes

            total = 0
            cache_dirs = [self._covers_dir, self._streams_dir, self._temp_dir]
            for c_dir in cache_dirs:
                if os.path.exists(c_dir):
                    for dirpath, _, filenames in os.walk(c_dir):
                        for f in filenames:
                            fp = os.path.join(dirpath, f)
                            try:
                                total += os.path.getsize(fp)
                            except OSError:
                                pass

            self._cached_size_bytes = total
            self._last_size_scan = now
            return total

    def get_cache_size_mb(self, force_rescan: bool = False) -> float:
        """Get total cache size in MB."""
        return self.get_cache_size(force_rescan=force_rescan) / (1024 * 1024)

    def mark_cache_dirty(self):
        """Reset size cache timestamp to trigger re-scan on next inquiry."""
        with self._size_cache_lock:
            self._last_size_scan = 0.0

    def get_storage_details(self) -> Dict[str, Any]:
        """
        Return comprehensive storage metrics (Decision 4).
        Returns: {used_bytes, quota_bytes, protected_count, quota_gb}
        """
        quota_gb = 5
        if self.settings:
            try:
                quota_gb = int(self.settings.get("storage", "cache_quota_gb", 5))
            except Exception:
                quota_gb = 5

        quota_bytes = quota_gb * 1024 * 1024 * 1024 if quota_gb > 0 else 0
        used_bytes = self.get_cache_size()

        # Count protected tracks (downloaded or favorites)
        protected_count = 0
        try:
            cursor = self.db.conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM tracks WHERE is_downloaded = 1 OR is_favorite = 1")
            row = cursor.fetchone()
            if row:
                protected_count = row[0]
        except Exception as e:
            self.logger.warning(f"Error querying protected tracks count: {e}")

        return {
            "used_bytes": used_bytes,
            "quota_bytes": quota_bytes,
            "quota_gb": quota_gb,
            "protected_count": protected_count
        }

    def clear_covers_cache(self):
        """Clear all cached cover art."""
        self._clear_dir(self._covers_dir)
        self.mark_cache_dirty()

    def clear_streams_cache(self):
        """Clear temporary cached stream files while preserving protected tracks."""
        self.purge_stream_cache(force_all_temporary=True)
        self.mark_cache_dirty()

    def clear_temp(self):
        """Clear temporary files."""
        self._clear_dir(self._temp_dir)
        self.mark_cache_dirty()

    def clear_all(self):
        """Clear all caches safely."""
        self.clear_covers_cache()
        self.clear_streams_cache()
        self.clear_temp()

    def _clear_dir(self, dir_path: str):
        """Remove files in a directory."""
        if os.path.exists(dir_path):
            for f in os.listdir(dir_path):
                fp = os.path.join(dir_path, f)
                try:
                    if os.path.isfile(fp):
                        os.remove(fp)
                    elif os.path.isdir(fp):
                        shutil.rmtree(fp)
                except OSError:
                    pass

    def purge_stream_cache(self, quota_bytes: Optional[int] = None, force_all_temporary: bool = False) -> int:
        """
        Intelligently purge temporary stream cache files according to LRU policy.
        - Strictly preserves files where is_downloaded = 1 OR is_favorite = 1.
        - Skips files currently being downloaded in _active_downloads.
        - Purges down to 75% of quota.
        - Updates DB stream_cache & tracks records in the same transaction.
        """
        if quota_bytes is None:
            quota_gb = 5
            if self.settings:
                try:
                    quota_gb = int(self.settings.get("storage", "cache_quota_gb", 5))
                except Exception:
                    quota_gb = 5
            quota_bytes = quota_gb * 1024 * 1024 * 1024 if quota_gb > 0 else 0

        # If quota is 0 (unlimited) and not forced, no purge needed
        if quota_bytes == 0 and not force_all_temporary:
            return 0

        total_used = self.get_cache_size(force_rescan=True)
        if not force_all_temporary and total_used <= quota_bytes:
            return 0

        target_bytes = int(quota_bytes * 0.75) if not force_all_temporary else 0

        # Step 1: Query protected file paths and source_ids from database
        protected_paths = set()
        protected_sources = set()
        try:
            cursor = self.db.conn.cursor()
            cursor.execute(
                "SELECT file_path, source, source_id FROM tracks WHERE is_downloaded = 1 OR is_favorite = 1"
            )
            for row in cursor.fetchall():
                fp = row[0]
                if fp:
                    protected_paths.add(os.path.normpath(fp).lower())
                src = row[1]
                src_id = row[2]
                if src and src_id:
                    protected_sources.add(f"{src}_{src_id}".lower())
        except Exception as e:
            self.logger.error(f"Error fetching protected tracks: {e}")

        # Step 2: Query active downloads under lock (Decision 2)
        with self._active_downloads_lock:
            active_downloads_copy = {d.lower() for d in self._active_downloads}

        # Step 3: Collect purge candidates from streams_dir
        candidates = []
        for dirpath, _, filenames in os.walk(self._streams_dir):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                norm_fp = os.path.normpath(fp).lower()
                base_name = os.path.splitext(f)[0].lower()

                # Check if protected
                if norm_fp in protected_paths:
                    continue
                if any(p_src in base_name for p_src in protected_sources):
                    continue
                if any(act in base_name for act in active_downloads_copy):
                    continue

                try:
                    stat = os.stat(fp)
                    candidates.append((fp, stat.st_mtime, stat.st_size))
                except OSError:
                    pass

        # Sort candidates by mtime ASC (oldest first - LRU)
        candidates.sort(key=lambda x: x[1])

        deleted_files = []
        freed_bytes = 0

        for fp, _, size in candidates:
            if not force_all_temporary and (total_used - freed_bytes) <= target_bytes:
                break
            try:
                os.remove(fp)
                freed_bytes += size
                deleted_files.append(fp)
            except OSError as oe:
                self.logger.debug(f"Failed to delete {fp}: {oe}")

        # Step 4: Synchronize DB in a single transaction (Decision 3)
        if deleted_files:
            try:
                with self.db.conn:
                    for dfp in deleted_files:
                        self.db.conn.execute(
                            "UPDATE stream_cache SET cached_file_path = NULL WHERE cached_file_path = ?",
                            (dfp,)
                        )
                        self.db.conn.execute(
                            "UPDATE tracks SET is_cached = 0, file_path = NULL "
                            "WHERE file_path = ? AND is_downloaded = 0 AND is_favorite = 0",
                            (dfp,)
                        )
            except Exception as dbe:
                self.logger.error(f"Error syncing DB after cache purge: {dbe}")

        self.mark_cache_dirty()
        self.logger.info(f"Purged {len(deleted_files)} cached streams, freed {freed_bytes / (1024 * 1024):.2f} MB")
        return freed_bytes

    def enforce_cache_limit(self, max_bytes: Optional[int] = None, max_mb: Optional[float] = None) -> int:
        """Evict least-recently-used stream cache files down to the quota.

        Thin delegate over purge_stream_cache(), which already implements the
        LRU policy, the protection of downloaded/favourite tracks and the DB
        synchronisation. `max_bytes` (or `max_mb`) overrides the configured
        quota; a quota of zero means "keep no temporary streams at all", and
        omitting both reads the quota from settings.
        Returns the number of bytes freed.
        """
        if max_bytes is None and max_mb is not None:
            max_bytes = int(max_mb * 1024 * 1024)
        if max_bytes is not None and max_bytes <= 0:
            return self.purge_stream_cache(force_all_temporary=True)
        return self.purge_stream_cache(quota_bytes=max_bytes)

    def download_audio_stream(self, source: str, source_id: str, url: str):
        """Asynchronously download audio stream to disk with active tracking and LRU enforcement."""
        download_id = f"{source}_{source_id}"
        with self._active_downloads_lock:
            if download_id in self._active_downloads:
                return
            self._active_downloads.add(download_id)

        # Enforce quota before starting new download
        self._executor.submit(self.purge_stream_cache)

        def _download_task():
            import yt_dlp
            try:
                out_template = os.path.join(self._streams_dir, f"{download_id}.%(ext)s")
                ydl_opts = {
                    'quiet': True,
                    'no_warnings': True,
                    'format': 'bestaudio/best',
                    'outtmpl': out_template,
                }

                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    if info:
                        ext = info.get('ext', 'm4a')
                        final_path = os.path.join(self._streams_dir, f"{download_id}.{ext}")
                        if os.path.exists(final_path):
                            self.logger.info(f"Successfully cached {source}/{source_id} to {final_path}")
                            self.db.set_cached_file(source, source_id, final_path)
                            self.mark_cache_dirty()
            except Exception as e:
                self.logger.error(f"Failed to cache {source}/{source_id}: {e}")
            finally:
                with self._active_downloads_lock:
                    self._active_downloads.discard(download_id)

        self._executor.submit(_download_task)

    def save_cover_from_url(self, url: str, track_id: int) -> Optional[str]:
        """Download and cache a cover image. Returns local path."""
        if not url or not isinstance(url, str):
            return None
        # Only remote http(s) images; anything else is either a local path the
        # caller should handle itself or a probe at internal schemes.
        if not url.startswith(("http://", "https://")):
            return None

        import urllib.request
        from urllib.parse import urlparse

        path = urlparse(url).path
        ext = os.path.splitext(path)[1]
        if not ext or ext.lower() not in ('.jpg', '.jpeg', '.png', '.webp'):
            ext = '.jpg'

        filepath = os.path.join(self._covers_dir, f"cover_{track_id}{ext}")
        if os.path.exists(filepath):
            return filepath

        # Download to temp first: an interrupted transfer used to leave a torn
        # image cached forever (the exists() check above would keep serving it).
        tmp_path = filepath + f".{os.getpid()}.part"
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as response, open(tmp_path, 'wb') as f:
                shutil.copyfileobj(response, f)
            if os.path.getsize(tmp_path) == 0:
                raise ValueError("empty cover response")
            os.replace(tmp_path, filepath)
            self.mark_cache_dirty()
            return filepath
        except Exception as e:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except OSError:
                pass
            self.logger.error(f"Failed to download cover from {url}: {e}")
            return None
