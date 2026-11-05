"""Bounded, cancellable BS.1770 loudness analysis of library files."""
import logging
import math
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)


def _lfilter_fallback(b, a, x, zi=None):
    """Direct Form II Transposed filter fallback when scipy.signal is unavailable."""
    import numpy as np

    b = np.asarray(b, dtype=np.float64) / a[0]
    a = np.asarray(a, dtype=np.float64) / a[0]
    order = max(len(a), len(b)) - 1
    if len(b) <= order:
        b = np.pad(b, (0, order + 1 - len(b)))
    if len(a) <= order:
        a = np.pad(a, (0, order + 1 - len(a)))
    y = np.empty_like(x, dtype=np.float64)
    z = np.zeros(order, dtype=np.float64) if zi is None else np.array(zi, dtype=np.float64, copy=True)
    for n in range(len(x)):
        xn = x[n]
        yn = b[0] * xn + z[0]
        y[n] = yn
        for m in range(order - 1):
            z[m] = b[m + 1] * xn - a[m + 1] * yn + z[m + 1]
        z[order - 1] = b[order] * xn - a[order] * yn
    return y.astype(x.dtype), z


def analyze_lufs(filepath, cancel_event=None, yield_callback=None):
    """Decode one second at a time, preserving native channels and filter state."""
    try:
        import miniaudio
        import numpy as np
        import pyloudnorm
        try:
            from scipy.signal import lfilter
        except (ImportError, ModuleNotFoundError) as err:
            logger.warning("scipy.signal.lfilter not available, using fallback: %s", err)
            lfilter = _lfilter_fallback
        info = miniaudio.get_file_info(filepath)
        channels, rate = info.nchannels, info.sample_rate
        if not 1 <= channels <= 5:
            raise ValueError('LUFS supports one to five native channels')
        meter = pyloudnorm.Meter(rate)
        stages = list(meter._filters.values())
        states = [[np.zeros(max(len(stage.a), len(stage.b)) - 1) for _ in range(channels)] for stage in stages]
        window, hop = int(rate * .4), int(rate * .1)
        pending = np.empty((0, channels), dtype=np.float32)
        energies, peak, frames = [], 0.0, 0
        stream = miniaudio.stream_file(filepath, output_format=miniaudio.SampleFormat.SIGNED16,
                                      nchannels=channels, sample_rate=rate, frames_to_read=rate)
        try:
            for samples in stream:
                if yield_callback is not None:
                    yield_callback()
                if cancel_event is not None and cancel_event.is_set():
                    raise InterruptedError('Analysis cancelled')
                data = np.asarray(samples, dtype=np.float32).reshape(-1, channels) / 32768.0
                if not len(data):
                    continue
                frames += len(data)
                peak = max(peak, float(np.max(np.abs(data))))
                for index, stage in enumerate(stages):
                    for channel in range(channels):
                        filtered, states[index][channel] = lfilter(stage.b, stage.a, data[:, channel], zi=states[index][channel])
                        data[:, channel] = filtered * stage.passband_gain
                pending = np.concatenate((pending, data))
                while len(pending) >= window:
                    energies.append(np.sum(np.square(pending[:window]), axis=0) / window)
                    pending = pending[hop:]
        finally:
            stream.close()
        if frames < window:
            raise ValueError('Audio shorter than the 400 ms measurement window')
        count = int(np.round(((frames / rate - .4) / .1))) + 1
        if len(energies) < count and len(pending):
            energies.append(np.sum(np.square(pending), axis=0) / window)
        z = np.asarray(energies, dtype=np.float64)
        weighted = z @ np.asarray([1, 1, 1, 1.41, 1.41][:channels])
        with np.errstate(divide='ignore'):
            levels = -.691 + 10 * np.log10(weighted)
        absolute = weighted[levels >= -70]
        if not len(absolute):
            raise ValueError('No finite loudness for silence')
        relative = -.691 + 10 * math.log10(float(absolute.mean())) - 10
        gated = weighted[(levels > relative) & (levels > -70)]
        if not len(gated):
            raise ValueError('No measurable audio')
        loudness = -.691 + 10 * math.log10(float(gated.mean()))
        if not math.isfinite(loudness) or not math.isfinite(peak):
            raise ValueError('Non-finite loudness')
        return float(loudness), float(peak), None
    except Exception as exc:
        return None, None, str(exc)


class LufsScannerService:
    RECONCILE_SECONDS = 6 * 60 * 60
    BATCH_SIZE = 20

    def __init__(self, app_core):
        self._core = app_core
        self._running = False
        self._thread = None
        self._stop = threading.Event()
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='LufsScanner')

    def start(self):
        if self._running or self._stop.is_set():
            return
        self._running = True
        self._thread = threading.Thread(target=self._scan_loop, daemon=True, name='LufsScanLoop')
        self._thread.start()

    def stop(self):
        self._running = False
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=5)
        self._pool.shutdown(wait=True, cancel_futures=True)

    def _scan_loop(self):
        if self._stop.wait(10):
            return
        last_id, next_reconcile = 0, 0
        while not self._stop.is_set():
            try:
                self._process_pending_batch()
                if time.monotonic() >= next_reconcile:
                    last_id, complete = self._reconcile_batch(last_id)
                    if complete:
                        last_id = 0
                        next_reconcile = time.monotonic() + self.RECONCILE_SECONDS
                self._stop.wait(.5 if last_id else 2)
            except Exception:
                logger.exception('LUFS scan loop error')
                self._stop.wait(10)

    def enqueue_path(self, path):
        """Watchdog modifications include rewrites of an already indexed path."""
        if not self._stop.is_set():
            self._core.db.enqueue_lufs_path(path)

    def _rows(self, where, values=(), pending=False):
        # Start at the tiny queue, never scan all tracks on the idle poll.
        tables = ('lufs_pending p CROSS JOIN tracks t ON t.id=p.track_id' if pending else
                  'tracks t LEFT JOIN lufs_pending p ON p.track_id=t.id')
        order = 'p.track_id' if pending else 't.id'
        return self._core.db.conn.execute('''SELECT t.id,t.file_path,a.file_path AS measured_path,
            a.mtime_ns,a.file_size,a.status,p.generation FROM ''' + tables + '''
            LEFT JOIN lufs_analysis a ON a.track_id=t.id WHERE ''' + where +
            f' ORDER BY {order} LIMIT ?', (*values, self.BATCH_SIZE)).fetchall()

    def _process_pending_batch(self):
        rows = self._rows("1=1", pending=True)
        for row in rows:
            if self._stop.is_set():
                break
            if self._process_row(row):
                db = self._core.db
                with db._write_lock, db.conn:
                    db.conn.execute('DELETE FROM lufs_pending WHERE track_id=? AND generation=?',
                                    (row['id'], row['generation']))
            if self._stop.wait(.05):
                break
        return len(rows)

    def _reconcile_batch(self, last_id):
        rows = self._rows("t.id>? AND NULLIF(t.file_path,'') IS NOT NULL", (last_id,))
        for row in rows:
            if self._stop.is_set():
                break
            last_id = row['id']
            self._process_row(row)
            if self._stop.wait(.05):
                break
        return last_id, len(rows) < self.BATCH_SIZE

    @staticmethod
    def _signature(path):
        try:
            info = os.stat(path)
            return info.st_mtime_ns, info.st_size
        except (OSError, TypeError):
            return None, None

    def _process_row(self, row):
        path = row['file_path']
        if not path:
            return True
        stamp, size = self._signature(path)
        if (row['measured_path'] == path and row['mtime_ns'] == stamp
                and row['file_size'] == size and row['status']):
            return True
        lufs, peak, error = (self._pool.submit(self._analyze_background, path).result()
                             if stamp is not None else (None, None, 'File missing'))
        if self._stop.is_set():
            return False
        # A writer may have changed the audio while it was decoded. Keep the
        # queue entry and do not publish a measurement of mixed file versions.
        if self._signature(path) != (stamp, size):
            self.enqueue_path(path)
            return False
        return self._update_db(row['id'], lufs, peak, path, stamp,
                               'failed' if error else 'measured', size)

    def _analyze_background(self, path):
        # Yield on every decoded second, including during a long song. This
        # changes scheduling only; every native sample still enters BS.1770.
        return analyze_lufs(path, self._stop, yield_callback=lambda: self._stop.wait(.02))

    def _update_db(self, track_id, lufs, peak, path=None, stamp=None, status='measured', file_size=None):
        if lufs is not None and not math.isfinite(lufs):
            lufs, peak, status = None, None, 'failed'
        db = self._core.db
        try:
            with db._write_lock, db.conn:
                updated = db.conn.execute('UPDATE tracks SET lufs=?,loudness_lufs=?,peak_volume=? WHERE id=? AND (? IS NULL OR file_path=?)',
                                         (lufs, lufs, peak, track_id, path, path))
                if not updated.rowcount:
                    return False
                if path is not None:
                    db.conn.execute('''INSERT OR REPLACE INTO lufs_analysis
                        (track_id,file_path,mtime_ns,status,file_size) VALUES (?,?,?,?,?)''',
                        (track_id, path, stamp, status, file_size))
            return True
        except Exception:
            logger.exception('Failed to save LUFS analysis')
            return False
