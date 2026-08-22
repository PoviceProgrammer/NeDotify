"""
NeDotify - LUFS Scanner Service
Analyzes local audio files in the background using miniaudio and pyloudnorm
to calculate ReplayGain values (LUFS).
"""

import os
import logging
import threading
import time
from concurrent.futures import ProcessPoolExecutor

logger = logging.getLogger(__name__)


def analyze_lufs(filepath: str) -> tuple:
    """Analyze a single audio file and return (loudness, peak, error)."""
    try:
        import miniaudio
        import pyloudnorm as pyln
        import numpy as np

        f = miniaudio.decode_file(filepath)
        audio_data = np.array(f.samples, dtype=np.float32) / 32768.0
        if f.nchannels > 1:
            audio_data = audio_data.reshape(-1, f.nchannels)
        rate = f.sample_rate
        meter = pyln.Meter(rate)
        loudness = meter.integrated_loudness(audio_data)
        peak = float(np.max(np.abs(audio_data)))
        return float(loudness), float(peak), None
    except Exception as e:
        return None, None, str(e)


class LufsScannerService:

    def __init__(self, app_core):
        self._core = app_core
        self._running = False
        self._thread = None
        self._pool = ProcessPoolExecutor(max_workers=max(1, os.cpu_count() // 2))

    def start(self):
        if self._running:
            return None
        self._running = True
        self._thread = threading.Thread(target=self._scan_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._pool:
            self._pool.shutdown(wait=False)

    def _scan_loop(self):
        time.sleep(10)
        while self._running:
            try:
                cursor = self._core.db.conn.cursor()
                cursor.execute("""
                    SELECT id, file_path FROM tracks 
                    WHERE source = 'local' 
                    AND lufs IS NULL 
                    AND file_path IS NOT NULL
                    LIMIT 20
                """)
                rows = cursor.fetchall()
                if not rows:
                    time.sleep(60)
                    continue
                futures = {}
                for row in rows:
                    track_id = row['id']
                    filepath = row['file_path']
                    if os.path.exists(filepath):
                        # M-9 fix: key by the future, not the track id
                        futures[self._pool.submit(analyze_lufs, filepath)] = track_id
                    else:
                        self._update_db(track_id, 0.0, 0.0)
                from concurrent.futures import as_completed
                for future in as_completed(futures):
                    track_id = futures[future]
                    try:
                        lufs, peak, err = future.result()
                        if lufs is not None:
                            self._update_db(track_id, lufs, peak)
                        else:
                            logger.error(f'LUFS scan failed for track {track_id}: {err}')
                            self._update_db(track_id, -14.0, 1.0)
                    except Exception as e:
                        logger.error(f'Error retrieving LUFS future for track {track_id}: {e}')
                        self._update_db(track_id, -14.0, 1.0)
            except Exception as e:
                logger.error(f'LUFS scan loop error: {e}')
                time.sleep(10)

    def _update_db(self, track_id, lufs, peak):
        try:
            self._core.db.conn.execute(
                'UPDATE tracks SET lufs = ?, loudness_lufs = ?, peak_volume = ? WHERE id = ?',
                (lufs, lufs, peak, track_id)
            )
            self._core.db.conn.commit()
            logger.debug(f'Saved LUFS {lufs:.2f} for track {track_id}')
        except Exception as e:
            logger.error(f'Failed to update LUFS DB: {e}')