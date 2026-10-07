"""Headless measurement child for the Python-side startup/idle profile.

Run as ``python tools/bench/pyprof_child.py <mode> [--json PATH]``. The parent
(``tools/bench/run_pyprof.py``) owns the scratch profile and the environment;
this module only measures. Nothing here ever touches ``webview.start()`` - the
GUI is never launched, so an already-running NeDotify instance is unaffected.

Modes
-----
``appcore_init``      wall-clock time of one ``AppCore()`` construction
``appcore_cprofile``  the same, wrapped in ``cProfile`` (sort='cumulative')
``appcore_breakdown`` per-step attribution via in-place ``__init__``/method
                      wrappers installed in this child only (no project file is
                      edited)
``idle``              N seconds of idle CPU with ``time.sleep`` /
                      ``threading.Event.wait`` / ``threading.Timer`` instrumented
                      so every wake can be counted with its real ``file:line``
``idle_hold``         construct ``AppCore`` then idle - a target for an external
                      sampler (``py-spy record --pid ...``)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Captured before any instrumentation so the harness's own waits are never
# mistaken for application sleeps.
_REAL_SLEEP = time.sleep


# ---------------------------------------------------------------------------
# profile isolation
# ---------------------------------------------------------------------------
def _redirect_profile(profile_root: str) -> str:
    """Point ``~`` at ``profile_root``.

    Every production path builds its state from ``os.path.expanduser("~") +
    ".nedotify"`` and the project has no ``NEDOTIFY_HOME``-style override. On
    Windows ``ntpath.expanduser`` reads ``USERPROFILE`` first, so re-pointing it
    (and clearing ``HOMEDRIVE``/``HOMEPATH``) moves the whole profile. This must
    run before *anything* imports a module that calls ``expanduser``.
    """
    p = Path(profile_root)
    p.mkdir(parents=True, exist_ok=True)
    os.environ["USERPROFILE"] = str(p)
    os.environ["HOMEDRIVE"] = ""
    os.environ["HOMEPATH"] = ""
    expanded = os.path.expanduser("~")
    if Path(expanded).resolve() != p.resolve():
        raise SystemExit(f"profile redirect failed: ~ is {expanded!r}, expected {str(p)!r}")
    return expanded


def _bootstrap() -> None:
    """Put the repo on ``sys.path`` and take this directory *off* it.

    ``tools/bench/profile.py`` (the fixture generator) shadows the stdlib
    ``profile`` module, which ``cProfile`` imports; with this script's own
    directory on ``sys.path`` that import resolves to the wrong file and
    ``cProfile`` dies with "module 'profile' has no attribute 'run'".
    """
    bench_dir = str(Path(__file__).resolve().parent)
    kept = []
    for entry in sys.path:
        try:
            same = Path(entry or ".").resolve() == Path(bench_dir)
        except OSError:
            same = False
        if not same:
            kept.append(entry)
    sys.path[:] = kept
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))


def _emit(payload: dict, out: str | None) -> None:
    text = json.dumps(payload, ensure_ascii=False)
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(text, encoding="utf-8")
    sys.stdout.write(text + "\n")
    sys.stdout.flush()


def _thread_snapshot() -> list[str]:
    return sorted(t.name for t in threading.enumerate())


# ---------------------------------------------------------------------------
# 1. AppCore construction - plain timing
# ---------------------------------------------------------------------------
def mode_appcore_init(args) -> None:
    import core.app as app_mod

    t0 = time.perf_counter()
    core = app_mod.AppCore()
    elapsed = time.perf_counter() - t0
    _emit(
        {
            "mode": "appcore_init",
            "seconds": elapsed,
            "ms": elapsed * 1000.0,
            "n_threads_after": len(_thread_snapshot()),
            "threads_after": _thread_snapshot(),
        },
        args.json,
    )
    del core


# ---------------------------------------------------------------------------
# 2. AppCore construction - cProfile
# ---------------------------------------------------------------------------
def mode_appcore_cprofile(args) -> None:
    import cProfile
    import pstats

    import core.app as app_mod

    prof = cProfile.Profile()
    t0 = time.perf_counter()
    prof.enable()
    core = app_mod.AppCore()
    prof.disable()
    elapsed = time.perf_counter() - t0

    out = Path(args.pstats)
    out.parent.mkdir(parents=True, exist_ok=True)
    prof.dump_stats(str(out))

    stats = pstats.Stats(prof)

    def rows(limit: int) -> list[dict]:
        got = []
        for (filename, lineno, name), (cc, nc, tt, ct, callers) in stats.stats.items():
            got.append(
                {
                    "file": _rel(filename) if filename != "~" else "<builtin>",
                    "line": lineno,
                    "func": name,
                    "ncalls": nc,
                    "tottime_ms": round(tt * 1000.0, 4),
                    "cumtime_ms": round(ct * 1000.0, 4),
                }
            )
        got.sort(key=lambda r: -r["cumtime_ms"])
        return got[:limit]

    def callers_of(limit: int) -> list[dict]:
        """Who called the most expensive entries - makes 'why' checkable.

        ``pstats`` stores ``stats[func] = (cc, nc, tt, ct, callers)`` and each
        ``callers[(file, line, name)] = (ncalls, cc, tt, ct)``.
        """
        out = []
        ranked = sorted(stats.stats.items(), key=lambda kv: -kv[1][3])[:limit]
        for (filename, lineno, name), (cc, nc, tt, ct, callers) in ranked:
            cs = sorted(callers.items(), key=lambda kv: -kv[1][3])[:3]
            out.append(
                {
                    "func": f"{_rel(filename) if filename != '~' else '<builtin>'}:{lineno}({name})",
                    "cumtime_ms": round(ct * 1000.0, 4),
                    "callers": [
                        {"from": f"{_rel(cf) if cf != '~' else '<builtin>'}:{cl}({cn})",
                         "calls": ccn, "cumtime_ms": round(cct * 1000.0, 4)}
                        for (cf, cl, cn), (ccn, ccc, ctt, cct) in cs
                    ],
                }
            )
        return out

    _emit(
        {
            "mode": "appcore_cprofile",
            "seconds": elapsed,
            "ms": elapsed * 1000.0,
            "pstats": str(out),
            "top_cumulative": rows(args.top),
            "top_tottime": sorted(rows(len(stats.stats)), key=lambda r: -r["tottime_ms"])[:args.top],
            "top_cumulative_callers": callers_of(10),
            "n_threads_after": len(_thread_snapshot()),
            "threads_after": _thread_snapshot(),
        },
        args.json,
    )
    del core


# ---------------------------------------------------------------------------
# 3. per-step attribution
# ---------------------------------------------------------------------------
def _wrap(owner, attr: str, label: str, sink: list) -> None:
    """In-place timing wrapper for a method on a class or a function on a module.

    The object is mutated inside *this child process only*; no project file is
    touched. Wall time is inclusive of nested work, which is what makes the
    per-step numbers additive against the total construction time.
    """
    orig = getattr(owner, attr)

    def wrapper(*a, **kw):
        t0 = time.perf_counter()
        try:
            return orig(*a, **kw)
        finally:
            sink.append({"label": label,
                         "ms": (time.perf_counter() - t0) * 1000.0,
                         "thread": threading.current_thread().name})

    wrapper.__name__ = getattr(orig, "__name__", attr)
    wrapper.__doc__ = orig.__doc__
    wrapper._pyprof_orig = orig
    setattr(owner, attr, wrapper)


def mode_appcore_breakdown(args) -> None:
    sink: list = []

    import audio.engine as engine_mod
    import core.app as app_mod
    import core.database as database_mod
    import core.downloader as downloader_mod
    import core.plugins as plugins_mod
    import core.proxy as proxy_mod
    import core.resolver as resolver_mod
    import core.services.discord_rpc as rpc_mod
    import core.session as session_mod
    import core.settings as settings_mod
    import services.artist_service as artist_mod
    import services.audio_fingerprint_service as afp_mod
    import services.lufs_scanner as lufs_mod
    import services.lyrics_service as lyrics_mod
    import services.playlist_import_service as plimp_mod
    import services.spotify_service as spotify_mod
    import services.vk_service as vk_mod
    import services.watchdog_service as wd_mod
    import services.youtube_service as yt_mod
    import services.zapret_service as zapret_mod
    import utils.cache_manager as cache_mod
    import utils.file_scanner as scanner_mod

    # -- constructors (core/app.py:106-136) -------------------------------
    for mod, cls in [
        (database_mod, "DatabaseManager"), (settings_mod, "SettingsManager"),
        (session_mod, "SessionManager"), (cache_mod, "CacheManager"),
        (scanner_mod, "FileScanner"), (resolver_mod, "StreamResolver"),
        (engine_mod, "AudioEngine"), (yt_mod, "YouTubeService"),
        (vk_mod, "VKService"), (spotify_mod, "SpotifyService"),
        (lyrics_mod, "LyricsService"), (artist_mod, "ArtistService"),
        (proxy_mod, "LocalProxyManager"), (downloader_mod, "DownloadManager"),
        (plugins_mod, "PluginManager"), (zapret_mod, "ZapretService"),
        (plimp_mod, "PlaylistImportService"), (wd_mod, "WatchdogService"),
        (lufs_mod, "LufsScannerService"), (afp_mod, "AudioFingerprintService"),
        (rpc_mod, "DiscordRPCService"),
    ]:
        _wrap(getattr(mod, cls), "__init__", f"{cls}()", sink)

    # -- work that AppCore hands to a background thread -------------------
    _wrap(yt_mod.YouTubeService, "_get_ydl", "YouTubeService._get_ydl() [executor task]", sink)

    # -- started work (core/app.py:137-174) -------------------------------
    _wrap(proxy_mod.LocalProxyManager, "start", "LocalProxyManager.start()", sink)
    _wrap(plugins_mod.PluginManager, "load_plugins", "PluginManager.load_plugins()", sink)
    _wrap(wd_mod.WatchdogService, "start", "WatchdogService.start()", sink)
    _wrap(lufs_mod.LufsScannerService, "start", "LufsScannerService.start()", sink)
    _wrap(rpc_mod.DiscordRPCService, "start", "DiscordRPCService.start()", sink)
    _wrap(zapret_mod.ZapretService, "auto_update_in_background",
          "ZapretService.auto_update_in_background()", sink)
    _wrap(app_mod, "update_ytdlp_safely", "update_ytdlp_safely() [thread body]", sink)

    # core/app.py looked these names up in its own globals, so re-bind them
    # there too - otherwise the wrappers would never be reached.
    for mod, cls_name in [
        (database_mod, "DatabaseManager"), (settings_mod, "SettingsManager"),
        (session_mod, "SessionManager"), (cache_mod, "CacheManager"),
        (scanner_mod, "FileScanner"), (resolver_mod, "StreamResolver"),
        (engine_mod, "AudioEngine"), (yt_mod, "YouTubeService"),
        (vk_mod, "VKService"), (spotify_mod, "SpotifyService"),
        (lyrics_mod, "LyricsService"), (artist_mod, "ArtistService"),
        (proxy_mod, "LocalProxyManager"), (downloader_mod, "DownloadManager"),
        (plugins_mod, "PluginManager"), (zapret_mod, "ZapretService"),
        (plimp_mod, "PlaylistImportService"), (wd_mod, "WatchdogService"),
        (lufs_mod, "LufsScannerService"), (afp_mod, "AudioFingerprintService"),
        (rpc_mod, "DiscordRPCService"),
    ]:
        setattr(app_mod, cls_name, getattr(mod, cls_name))

    t0 = time.perf_counter()
    core = app_mod.AppCore()
    elapsed = (time.perf_counter() - t0) * 1000.0

    # ``YouTubeService.__init__`` hands ``_get_ydl`` to its own
    # ThreadPoolExecutor, so that cost lands *after* the constructor returns.
    # Wait (bounded) for it so it is attributed instead of being lost.
    drain_deadline = time.perf_counter() + args.drain
    while time.perf_counter() < drain_deadline:
        if any(r["label"].endswith("[executor task]") for r in sink):
            break
        time.sleep(0.005)
    drain_ms = (time.perf_counter() - t0) * 1000.0 - elapsed

    agg: dict = {}
    for row in sink:
        a = agg.setdefault(row["label"], {"label": row["label"], "ms_total": 0.0,
                                         "calls": 0, "threads": set()})
        a["ms_total"] += row["ms"]
        a["calls"] += 1
        a["threads"].add(row["thread"])
    rows = [{"label": a["label"], "ms_total": round(a["ms_total"], 3),
             "calls": a["calls"], "threads": sorted(a["threads"])}
            for a in agg.values()]
    rows.sort(key=lambda r: -r["ms_total"])

    _emit(
        {
            "mode": "appcore_breakdown",
            "total_ms": round(elapsed, 3),
            "async_drain_ms": round(drain_ms, 3),
            "n_threads_after": len(_thread_snapshot()),
            "threads_after": _thread_snapshot(),
            "steps": rows,
        },
        args.json,
    )
    del core


# ---------------------------------------------------------------------------
# 4. idle CPU + wake counting
# ---------------------------------------------------------------------------
def _rel(path: str) -> str:
    """Repo-relative path when possible, else the bare file name."""
    try:
        return Path(path).resolve().relative_to(REPO_ROOT).as_posix()
    except (ValueError, OSError):
        return Path(path).name


def _caller(depth: int = 2) -> str:
    try:
        f = sys._getframe(depth)
        return f"{_rel(f.f_code.co_filename)}:{f.f_lineno}"
    except Exception:
        return "?"


class _WakeLog:
    """Records every ``time.sleep`` / ``Event.wait`` / ``Timer`` with its caller.

    This is the measurement instrument for "how often does each background loop
    actually wake". Because every module in the project does ``import time`` then
    ``time.sleep(...)`` - i.e. the attribute is resolved on the shared ``time``
    module object at call time - rebinding ``time.sleep`` in this child counts
    the real calls without touching any source file.
    """

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.sleeps: dict = {}
        self.waits: dict = {}
        self.timers_created: list = []

    def install(self) -> None:
        log = self
        real_sleep = time.sleep
        real_wait = threading.Event.wait
        real_timer = threading.Timer
        self._restore = (real_sleep, real_wait, real_timer)

        def counting_sleep(seconds=0, *a, **kw):
            key = _caller(2)
            with log.lock:
                row = log.sleeps.setdefault(key, {"calls": 0, "blocked_s": 0.0,
                                                  "declared_s": {}})
                row["calls"] += 1
                d = _fmt_arg(seconds)
                row["declared_s"][d] = row["declared_s"].get(d, 0) + 1
            t0 = time.perf_counter()
            real_sleep(seconds, *a, **kw)
            with log.lock:
                log.sleeps[key]["blocked_s"] += time.perf_counter() - t0

        def counting_wait(self, timeout=None):
            key = _caller(2)
            # Event.wait is also reached from threading's own internals
            # (Thread.join -> _wait_for_tstate_lock), so record who wanted the
            # wait one frame further up; that is what decides "app" vs
            # "measurement harness".
            origin = _caller(3)
            t0 = time.perf_counter()
            rv = real_wait(self, timeout)
            dt = time.perf_counter() - t0
            with log.lock:
                row = log.waits.setdefault(key, {"calls": 0, "blocked_s": 0.0,
                                                 "timeout_wakes": 0, "declared": {},
                                                 "origins": {}})
                row["calls"] += 1
                row["blocked_s"] += dt
                # A wait that ran >=95% of its declared timeout was a pure
                # timeout wake, not a wake caused by another thread.
                if timeout is not None and timeout > 0 and dt >= timeout * 0.95:
                    row["timeout_wakes"] += 1
                d = _fmt_arg(timeout)
                row["declared"][d] = row["declared"].get(d, 0) + 1
                row["origins"][origin] = row["origins"].get(origin, 0) + 1
            return rv

        class counting_timer(real_timer):  # type: ignore[misc, valid-type]
            def __init__(self, interval, function, *a, **kw):
                with log.lock:
                    log.timers_created.append({"interval_s": _fmt_arg(interval),
                                               "site": _caller(2)})
                super().__init__(interval, function, *a, **kw)

        time.sleep = counting_sleep
        threading.Event.wait = counting_wait
        threading.Timer = counting_timer

    def uninstall(self) -> None:
        real_sleep, real_wait, real_timer = self._restore
        time.sleep = real_sleep
        threading.Event.wait = real_wait
        threading.Timer = real_timer

    def snapshot(self) -> dict:
        """Split the log into application and measurement-harness wakes."""
        with self.lock:
            sleeps = {k: dict(v) for k, v in self.sleeps.items()}
            waits = {k: dict(v) for k, v in self.waits.items()}
            timers = list(self.timers_created)

        def is_harness(site: str) -> bool:
            return site.startswith("tools/bench/")

        harness_waits = {}
        app_waits = {}
        for site, row in waits.items():
            # A stdlib threading internal belongs to whoever asked for it.
            owner = max(row["origins"].items(), key=lambda kv: kv[1])[0] \
                if row["origins"] else site
            if is_harness(site) or is_harness(owner):
                harness_waits[site] = dict(row, attributed_to=owner)
            else:
                app_waits[site] = dict(row, attributed_to=owner)
        return {
            "app": {"sleeps": {k: v for k, v in sleeps.items()
                               if not is_harness(k)},
                    "event_waits": app_waits,
                    "timers_created": timers},
            "harness": {"sleeps": {k: v for k, v in sleeps.items()
                                   if is_harness(k)},
                        "event_waits": harness_waits},
        }


def _fmt_arg(v) -> str:
    try:
        return repr(float(v))
    except (TypeError, ValueError):
        return repr(v)


def _cpu_times() -> dict:
    import psutil
    p = psutil.Process()
    t = p.cpu_times()
    return {"user": t.user, "system": t.system, "total": t.user + t.system,
            "threads": p.num_threads()}


def _os_thread_cpu() -> dict:
    """Per-OS-thread CPU accounting.

    ``psutil.Process.threads()`` works on Windows and reports user/system time
    per thread id, and on Windows ``threading.get_ident()`` *is* that OS thread
    id - so Python threads can be named and the rest identified as non-Python
    (native) threads. This is what makes per-thread idle attribution possible
    without py-spy. Granularity is the 15.625 ms Windows clock tick.
    """
    import psutil
    out = {}
    for t in psutil.Process().threads():
        out[t.id] = {"user": t.user_time, "system": t.system_time,
                     "total": t.user_time + t.system_time,
                     "create_time": getattr(t, "create_time", None)}
    return out


def _py_thread_names() -> dict:
    return {t.ident: t.name for t in threading.enumerate()}


def _idle_window(args, log: _WakeLog, build_ms: float | None) -> dict:
    """Shared idle measurement.

    The psutil sampling runs on a dedicated *helper* thread so that
    ``MainThread`` spends the whole window in one uninterrupted sleep. Otherwise
    the harness' own polling would be charged to ``MainThread`` and the biggest
    idle consumer in the process would be the measuring instrument. The helper's
    own CPU is reported separately and subtracted.
    """
    real_sleep = _REAL_SLEEP
    helper: dict = {}
    done = threading.Event()

    cpu_after_build = _cpu_times()
    names_after_build = _py_thread_names()
    os_after_build = _os_thread_cpu()

    def sampler() -> None:
        """Owns the whole measurement window, including both snapshots.

        Both endpoint snapshots are taken here on purpose: if the *end* snapshot
        were taken by MainThread after the join, the sampler thread would already
        be gone and its own CPU (which is real, and has to be subtracted) would
        be unreportable - and MainThread would be charged for the psutil calls.
        """
        helper["tid"] = threading.get_ident()
        # Warm-up: right after construction the background threads are still
        # settling (discord IPC attempt at +0s, zapret's deliberate 5 s delay,
        # the LUFS scanner's 10 s first pass). "Idle" means steady state.
        real_sleep(args.settle)
        settle_cpu = _cpu_times()["total"] - cpu_after_build["total"]
        os_settled = _os_thread_cpu()
        cpu_settled = _cpu_times()
        names_settled = _py_thread_names()
        t0 = time.perf_counter()
        samples = []
        while time.perf_counter() - t0 < args.seconds:
            real_sleep(1.0)
            samples.append(_cpu_times())
        window = time.perf_counter() - t0
        os_end = _os_thread_cpu()
        cpu_end = _cpu_times()
        names_end = _py_thread_names()
        helper.update(window=window, samples=samples, cpu_settled=cpu_settled,
                      cpu_end=cpu_end, os_settled=os_settled, os_end=os_end,
                      names_settled=names_settled, names_end=names_end,
                      settle_cpu=settle_cpu)
        done.set()

    t = threading.Thread(target=sampler, name="IdleSampler", daemon=True)
    t.start()
    # MainThread is a no-op for the whole window: no CPU charged to it here.
    deadline = time.perf_counter() + args.settle + args.seconds + 2.0
    while not done.is_set() and time.perf_counter() < deadline:
        real_sleep(0.25)
    t.join(timeout=30)
    done.wait(timeout=5)
    if not done.is_set():
        raise SystemExit("idle sampler did not finish in time")

    window = helper["window"]
    cpu_settled = helper["cpu_settled"]
    cpu_end = helper["cpu_end"]
    os_settled = helper["os_settled"]
    os_end = helper["os_end"]
    names_end = helper["names_end"]
    total = cpu_end["total"] - cpu_settled["total"]

    # per-OS-thread idle CPU, mapped to Python thread names where possible.
    # A tid with no Python name is a native thread created by a C extension
    # (asyncio proactor, watchdog's ReadDirectoryChangesW emitter, ...).
    all_names: dict = {}
    for src in (helper["names_settled"], names_after_build, names_end):
        all_names.update(src)
    # threads that existed at one end only, for completeness
    vanished = sorted(set(os_settled) ^ set(os_end))
    per_thread_all = []
    for tid in sorted(set(os_settled) | set(os_end)):
        start_row = os_settled.get(tid, {}).get("total")
        end_row = os_end.get(tid, {}).get("total")
        if start_row is None or end_row is None:
            continue  # thread appeared/disappeared inside the window
        delta = end_row - start_row
        per_thread_all.append({
            "tid": tid,
            "name": all_names.get(tid, "<native: C-extension thread>"),
            "is_harness": tid == helper["tid"],
            "idle_cpu_s": round(delta, 6),
            "idle_cpu_pct_of_one_core": round(delta / window * 100.0, 4),
        })
    per_thread_all.sort(key=lambda r: -r["idle_cpu_s"])
    harness_row = next((r for r in per_thread_all if r["tid"] == helper["tid"]), None)
    harness_cpu = harness_row["idle_cpu_s"] if harness_row else 0.0
    per_thread_all = [r for r in per_thread_all if not r["is_harness"]]

    deltas = []
    prev = cpu_settled
    for s in helper["samples"]:
        deltas.append({"dt_cpu_s": round(s["total"] - prev["total"], 6),
                       "threads": s["threads"]})
        prev = s

    return {
        "mode": "idle",
        "build_ms": round(build_ms, 3) if build_ms is not None else None,
        "settle_s": args.settle,
        "settle_cpu_s": round(helper["settle_cpu"], 4),
        "window_s": round(window, 2),
        "cpu_after_build_total_s": round(cpu_after_build["total"], 4),
        "cpu_at_settle_total_s": round(cpu_settled["total"], 4),
        "cpu_at_end_total_s": round(cpu_end["total"], 4),
        "idle_window_cpu_s": round(total, 4),
        "idle_window_cpu_pct_of_one_core": round(total / window * 100.0, 4),
        "harness_cpu_s": round(harness_cpu, 6),
        "idle_window_cpu_s_excl_harness": round(total - harness_cpu, 4),
        "idle_window_cpu_pct_excl_harness": round((total - harness_cpu) / window * 100.0, 4),
        "os_threads_created_during_build": len(os_after_build),
        "os_thread_count_at_settle": len(os_settled),
        "os_thread_count_at_end": len(os_end),
        "os_tids_only_at_one_end": vanished,
        "cpu_tick_resolution_s": 0.015625,
        "per_sample_cpu_delta_s": deltas,
        "per_os_thread_idle_all": per_thread_all,
        "wake_log": log.snapshot(),
        "thread_names": _thread_snapshot(),
    }


def mode_idle(args) -> None:
    import core.app as app_mod

    t0 = time.perf_counter()
    core = app_mod.AppCore()
    build_ms = (time.perf_counter() - t0) * 1000.0

    log = _WakeLog()
    log.install()
    payload = _idle_window(args, log, build_ms)
    log.uninstall()
    _emit(payload, args.json)
    del core


def mode_idle_control(args) -> None:
    """Identical window with NO AppCore - the harness/process floor."""
    log = _WakeLog()
    log.install()
    payload = _idle_window(args, log, None)
    log.uninstall()
    _emit(payload, args.json)


def mode_idle_hold(args) -> None:
    """Construct AppCore, print the pid, then idle - a target for py-spy."""
    import core.app as app_mod

    core = app_mod.AppCore()
    sys.stdout.write(json.dumps({"pid": os.getpid(),
                                 "threads": _thread_snapshot()}) + "\n")
    sys.stdout.flush()
    deadline = time.perf_counter() + args.seconds
    while time.perf_counter() < deadline:
        time.sleep(0.5)
    del core


# ---------------------------------------------------------------------------
MODES = {
    "appcore_init": mode_appcore_init,
    "appcore_cprofile": mode_appcore_cprofile,
    "appcore_breakdown": mode_appcore_breakdown,
    "idle": mode_idle,
    "idle_control": mode_idle_control,
    "idle_hold": mode_idle_hold,
}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("mode", choices=sorted(MODES))
    ap.add_argument("--profile", required=True,
                    help="scratch profile root; USERPROFILE is pointed here")
    ap.add_argument("--json", default=None, help="also write the JSON payload here")
    ap.add_argument("--pstats", default=None, help="cProfile output (.pstats)")
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--settle", type=float, default=10.0)
    ap.add_argument("--drain", type=float, default=10.0,
                    help="breakdown: bounded wait for post-constructor executor work")
    args = ap.parse_args(argv)

    _redirect_profile(args.profile)
    _bootstrap()
    if args.mode == "appcore_cprofile" and not args.pstats:
        ap.error("--pstats is required for appcore_cprofile")

    MODES[args.mode](args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())