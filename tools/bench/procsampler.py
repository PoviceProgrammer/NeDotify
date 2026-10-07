"""Process-tree CPU/RAM sampler for the NeDotify benchmark.

Reports the Python process *and* its WebView2 renderer/GPU children, because
the renderer's CPU is where frontend regressions actually show up. Measuring
only the Python process would understate real cost by a wide margin.

``psutil`` is used here (owner-approved as a dev-only tool); it is not added to
requirements.txt because nothing in the shipped app imports it.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None

WEBVIEW2_MARKERS = ("msedgewebview2.exe",)


@dataclass
class Sample:
    t: float
    python_cpu_pct: float = 0.0
    webview_cpu_pct: float = 0.0
    tree_cpu_pct: float = 0.0
    python_rss_mb: float = 0.0
    webview_rss_mb: float = 0.0
    tree_rss_mb: float = 0.0
    python_threads: int = 0
    n_children: int = 0


@dataclass
class ProcSampler:
    """Samples a process tree on a fixed interval."""

    interval: float = 1.0
    pid: int = field(default_factory=os.getpid)
    samples: list[Sample] = field(default_factory=list)
    _stop: threading.Event = field(default_factory=threading.Event)
    _thread: threading.Thread | None = None
    # pid -> (cumulative cpu seconds, monotonic timestamp of that reading)
    _last: dict = field(default_factory=dict)

    def _tree_pids(self, root: int) -> tuple[int, list[int]]:
        if psutil is None:
            return root, []
        try:
            children = psutil.Process(root).children(recursive=True)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return root, []
        return root, [c.pid for c in children if _is_webview2(c)]

    def _read(self, pid: int):
        """Cumulative CPU seconds + RSS for one pid, or None if it is gone."""
        try:
            p = psutil.Process(pid)
            with p.oneshot():
                t = p.cpu_times()
                rss = p.memory_info().rss / (1024 * 1024)
                thr = p.num_threads()
            return (t.user + t.system), rss, thr
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return None

    def _take(self) -> Sample:
        """One sample: CPU % derived by differencing cumulative CPU seconds.

        Deliberately not using ``Process.cpu_percent(interval=None)``: that value
        depends on psutil's internal per-Process cache, and ``oneshot()`` can
        recycle that object - which is why an early run reported a flat 0.00 %
        idle CPU on a process that was demonstrably burning CPU. Differencing
        ``cpu_times()`` against our own previous reading is self-contained and
        reproducible.
        """
        s = Sample(t=time.monotonic())
        if psutil is None:
            return s
        root_pid, child_pids = self._tree_pids(self.pid)

        got = self._read(root_pid)
        if got:
            cpu_seconds, rss, thr = got
            s.python_rss_mb = rss
            s.python_threads = thr
            prev = self._last.get(root_pid)
            if prev:
                d_cpu = cpu_seconds - prev[0]
                d_wall = s.t - prev[1]
                if d_wall > 0:
                    s.python_cpu_pct = max(0.0, (d_cpu / d_wall) * 100.0)
            self._last[root_pid] = (cpu_seconds, s.t)

        for cpid in child_pids:
            got = self._read(cpid)
            if not got:
                continue
            cpu_seconds, rss, _thr = got
            s.webview_rss_mb += rss
            prev = self._last.get(cpid)
            if prev:
                d_cpu = cpu_seconds - prev[0]
                d_wall = s.t - prev[1]
                if d_wall > 0:
                    s.webview_cpu_pct += max(0.0, (d_cpu / d_wall) * 100.0)
            self._last[cpid] = (cpu_seconds, s.t)

        s.n_children = len(child_pids)
        s.tree_cpu_pct = s.python_cpu_pct + s.webview_cpu_pct
        s.tree_rss_mb = s.python_rss_mb + s.webview_rss_mb
        return s

    def _loop(self) -> None:
        # discard one sample so the first recorded one has a real interval
        self._take()
        while not self._stop.is_set():
            self._stop.wait(self.interval)
            if self._stop.is_set():
                break
            self.samples.append(self._take())

    def _prime(self) -> None:
        """Take a baseline reading before any sample is recorded."""
        if psutil is None:
            return
        for _ in range(2):
            self._take()
            time.sleep(0.4)

    def start(self) -> "ProcSampler":
        if psutil is None:
            return self
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="ProcSampler", daemon=True)
        self._thread.start()
        self._prime()
        return self

    def stop(self) -> list[Sample]:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5.0)
        return self.samples

    # -- summaries ---------------------------------------------------------
    def summary(self, warmup: float = 0.0) -> dict:
        """Mean/median CPU and peak RAM over the sampled window.

        ``warmup`` drops the first N seconds (page load, asset decode) so the
        idle figure reflects steady state rather than first-paint work.
        """
        rows = self.samples
        if warmup and rows:
            cutoff = rows[0].t + warmup
            rows = [r for r in rows if r.t >= cutoff]
        if not rows:
            return {}

        def stat(vals: list[float]) -> dict:
            vs = sorted(vals)
            n = len(vs)
            return {
                "mean": round(sum(vs) / n, 2),
                "median": round(vs[n // 2], 2) if n % 2 else round((vs[n // 2 - 1] + vs[n // 2]) / 2, 2),
                "p95": round(vs[min(n - 1, int(n * 0.95))], 2),
                "max": round(vs[-1], 2),
            }

        return {
            "n_samples": len(rows),
            "window_sec": round(rows[-1].t - rows[0].t, 1),
            "python_cpu_pct": stat([r.python_cpu_pct for r in rows]),
            "webview_cpu_pct": stat([r.webview_cpu_pct for r in rows]),
            "tree_cpu_pct": stat([r.tree_cpu_pct for r in rows]),
            "python_rss_mb": stat([r.python_rss_mb for r in rows]),
            "webview_rss_mb": stat([r.webview_rss_mb for r in rows]),
            "tree_rss_mb": stat([r.tree_rss_mb for r in rows]),
            "python_threads_max": max(r.python_threads for r in rows),
            "n_children_max": max(r.n_children for r in rows),
        }


def _is_webview2(proc) -> bool:
    try:
        name = (proc.name() or "").lower()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False
    return name in WEBVIEW2_MARKERS
