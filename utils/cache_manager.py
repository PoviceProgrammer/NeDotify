"""
NeDotify - Cache Manager
Manages cover art cache, stream URL cache, and metadata cache.
"""

import os
import shutil
import time
import logging
import concurrent.futures
import traceback
from core.database import DatabaseManager


class CacheManager:
    """Manages local caching of covers, stream URLs, and downloaded audio."""

    def __init__(self, db: DatabaseManager):
        self.db = db
        self._base_dir = os.path.join(os.path.expanduser("~"), ".nedotify")
        # Store covers inside ui/web_new/covers so WebView can resolve them via relative paths
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self._covers_dir = os.path.abspath(os.path.join(project_root, "ui", "web_new", "covers"))
        self._streams_dir = os.path.join(self._base_dir, "streams")
        self._temp_dir = os.path.join(self._base_dir, "temp")

        # Ensure directories exist
        for d in [self._covers_dir, self._streams_dir, self._temp_dir]:
            os.makedirs(d, exist_ok=True)
            
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)
        self._active_downloads = set()
        self.logger = logging.getLogger("CacheManager")

    @property
    def covers_dir(self) -> str:
        return self._covers_dir

    @property
    def streams_dir(self) -> str:
        return self._streams_dir

    @property
    def temp_dir(self) -> str:
        return self._temp_dir

    def get_cache_size(self) -> int:
        """Get total cache size in bytes."""
        total = 0
        for dirpath, dirnames, filenames in os.walk(self._base_dir):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                try:
                    total += os.path.getsize(fp)
                except OSError:
                    pass
        return total

    def get_cache_size_mb(self) -> float:
        """Get total cache size in MB."""
        return self.get_cache_size() / (1024 * 1024)

    def clear_covers_cache(self):
        """Clear all cached cover art."""
        self._clear_dir(self._covers_dir)

    def clear_streams_cache(self):
        """Clear all cached stream files."""
        self._clear_dir(self._streams_dir)

    def clear_temp(self):
        """Clear temporary files."""
        self._clear_dir(self._temp_dir)

    def clear_all(self):
        """Clear all caches."""
        self.clear_covers_cache()
        self.clear_streams_cache()
        self.clear_temp()

    def _clear_dir(self, dir_path: str):
        """Remove all files in a directory."""
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

    def download_audio_stream(self, source: str, source_id: str, url: str):
        """Asynchronously download audio stream to disk without re-encoding."""
        download_id = f"{source}_{source_id}"
        if download_id in self._active_downloads:
            return  # Already downloading

        # First, ensure we haven't exceeded cache limit before starting a new download
        self._executor.submit(self.enforce_cache_limit)

        def _download_task():
            import yt_dlp
            self._active_downloads.add(download_id)
            try:
                # We'll download directly into a .tmp file.
                # Since yt-dlp handles extensions automatically based on format,
                # we can use '%(id)s.%(ext)s.tmp' but yt-dlp might complain if postprocessing.
                # Actually, if we use bestaudio, we don't postprocess!
                # So we can just output to '%(id)s.%(ext)s' and yt-dlp will save it.
                # BUT wait, we want atomic rename.
                # By default, yt-dlp downloads to `.part` and then renames to the final file!
                # So yt-dlp's default behavior IS atomic! It won't leave a half-finished file without `.part` or `.ytdl` extension.
                # However, to be absolutely safe and to easily track it in our DB, we'll force the output to a specific temp name,
                # or just let yt-dlp do its atomic rename and we detect the final filename.
                
                out_template = os.path.join(self._streams_dir, f"{download_id}.%(ext)s")
                
                ydl_opts = {
                    'quiet': True,
                    'no_warnings': True,
                    'format': 'bestaudio/best',
                    'outtmpl': out_template,
                    # DO NOT extract audio / transcode to mp3 to save CPU!
                    # yt-dlp will save as webm or m4a automatically.
                }

                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    if info:
                        ext = info.get('ext', 'm4a')
                        final_path = os.path.join(self._streams_dir, f"{download_id}.{ext}")
                        if os.path.exists(final_path):
                            self.logger.info(f"Successfully cached {source}/{source_id} to {final_path}")
                            # Update DB
                            self.db.set_cached_file(source, source_id, final_path)
            except Exception as e:
                self.logger.error(f"Failed to cache {source}/{source_id}: {e}")
            finally:
                self._active_downloads.remove(download_id)

        self._executor.submit(_download_task)

    def save_cover_from_url(self, url: str, track_id: int) -> str:
        """Download and cache a cover image. Returns local path."""
        if not url:
            return None
            
        import urllib.request
        from urllib.parse import urlparse
        import logging
        
        logger = logging.getLogger(__name__)
        
        # Determine extension from url, default to .jpg
        path = urlparse(url).path
        ext = os.path.splitext(path)[1]
        if not ext or ext.lower() not in ('.jpg', '.jpeg', '.png', '.webp'):
            ext = '.jpg'
            
        filepath = os.path.join(self._covers_dir, f"cover_{track_id}{ext}")
        
        # If it already exists, just return it
        if os.path.exists(filepath):
            return filepath
            
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as response:
                with open(filepath, 'wb') as f:
                    shutil.copyfileobj(response, f)
            return filepath
        except Exception as e:
            logger.error(f"Failed to download cover from {url}: {e}")
            return None

    def enforce_cache_limit(self, max_mb: int = 500):
        """Remove oldest cached files if cache exceeds limit."""
        current_mb = self.get_cache_size_mb()
        if current_mb <= max_mb:
            return

        # Get all cached files sorted by modification time
        files = []
        for dirpath, _, filenames in os.walk(self._streams_dir):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                try:
                    files.append((fp, os.path.getmtime(fp), os.path.getsize(fp)))
                except OSError:
                    pass

        files.sort(key=lambda x: x[1])  # Oldest first

        freed = 0
        target_free = (current_mb - max_mb) * 1024 * 1024
        for fp, _, size in files:
            if freed >= target_free:
                break
            try:
                os.remove(fp)
                freed += size
            except OSError:
                pass
