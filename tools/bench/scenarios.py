"""Scenario definitions for the NeDotify benchmark.

Each scenario receives a :class:`BenchContext` and returns a JSON-serialisable
dict. Scenarios must be hermetic: no network, no writes outside the scratch
profile, no dependence on wall-clock time or random data.

Timings are taken from inside the renderer via CDP ``Runtime.evaluate`` and
``performance.now()`` wherever possible, because Python-side wall clock cannot
see when a frame was actually painted.
"""

from __future__ import annotations

import statistics
import time


# --------------------------------------------------------------------------
# Window state control (needed for the "window minimised" idle requirement)
# --------------------------------------------------------------------------
SW_MINIMIZE = 6
SW_RESTORE = 9


def find_main_window(title: str = "NeDotify"):
    """HWND of the app's top-level window, or None.

    CDP cannot minimise a native window, so the minimised-idle figure has to be
    taken through Win32. Enumerating by title is fragile in general, but the
    title is set in main.py's create_window and the bench runs exactly one
    instance (the single-instance mutex guarantees it).
    """
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    found: list[int] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def _cb(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length:
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            if title.lower() in buf.value.lower():
                found.append(hwnd)
        return True

    user32.EnumWindows(_cb, 0)
    return found[0] if found else None


def set_window_minimized(hwnd, minimized: bool) -> bool:
    import ctypes
    user32 = ctypes.windll.user32
    if not hwnd:
        return False
    user32.ShowWindow(hwnd, SW_MINIMIZE if minimized else SW_RESTORE)
    return True


def _summarise(rows) -> dict:
    """Same statistics as ProcSampler.summary(), but over an explicit row list.

    Needed because the state-by-state scenario must summarise a slice of the
    sample stream rather than the whole thing.
    """
    if not rows:
        return {}
    saved, ctx_rows = None, rows

    def stat(vals):
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


BACKDROP_LIVE_JS = r"""
(() => {
  const out = [];
  const vw = window.innerWidth, vh = window.innerHeight;
  document.querySelectorAll('*').forEach(el => {
    const cs = getComputedStyle(el);
    const bf = cs.backdropFilter || cs.webkitBackdropFilter || 'none';
    if (!bf || bf === 'none') return;
    const r = el.getBoundingClientRect();
    const w = Math.max(0, Math.min(r.right, vw) - Math.max(r.left, 0));
    const h = Math.max(0, Math.min(r.bottom, vh) - Math.max(r.top, 0));
    out.push({
      tag: el.tagName.toLowerCase(),
      id: el.id || '',
      cls: String(el.className || '').slice(0, 70),
      backdropFilter: bf,
      background: cs.backgroundColor,
      opacity: cs.opacity,
      clippedArea: Math.round(w * h),
      onScreen: w > 0 && h > 0,
      display: cs.display,
      visibility: cs.visibility,
      zIndex: cs.zIndex,
    });
  });
  out.sort((a, b) => b.clippedArea - a.clippedArea);
  return { count: out.length, viewport: [vw, vh], elements: out };
})()
"""


CDP_DELTA_KEYS = (
    "TaskDuration", "ScriptDuration", "LayoutDuration", "RecalcStyleDuration",
    "LayoutCount", "RecalcStyleCount", "Nodes", "JSEventListeners",
    "LayoutObjects", "JSHeapUsedSize",
)


def _perf_delta(ctx, seconds: float) -> dict:
    """CDP Performance counters differenced across an idle window.

    Decides *what kind* of work the idle CPU is: a growing ScriptDuration means
    a JS rAF loop is burning the main thread, while growing LayoutCount /
    RecalcStyleCount with a flat ScriptDuration means the renderer is being
    asked to re-raster and re-composite - which is what makes every
    backdrop-filter surface re-sample its backdrop.
    """
    before = ctx.perf_metrics()
    t0 = time.monotonic()
    time.sleep(seconds)
    after = ctx.perf_metrics()
    out = {"window_sec": round(time.monotonic() - t0, 2)}
    for k in CDP_DELTA_KEYS:
        b, a = before.get(k), after.get(k)
        if isinstance(b, (int, float)) and isinstance(a, (int, float)):
            out[k] = round(a - b, 4)
    return out


def scenario_backdrop_live(ctx) -> dict:
    """Which elements have an ACTIVE backdrop-filter right now, and how big.

    Static CSS analysis is not enough: `#main-content`, named in the static
    ranking as a full-bleed backdrop-filter root, only gets one under
    `html.has-custom-bg` (base.css:372) - in the default theme it has none at
    all. This reads computed style from the live DOM instead, so the list is
    what the compositor is actually paying for, ranked by on-screen area.
    """
    raw = ctx.js(BACKDROP_LIVE_JS, timeout=30.0) or {}
    els = raw.get("elements", [])
    on_screen = [e for e in els if e["onScreen"]]
    return {
        "viewport": raw.get("viewport"),
        "total_with_backdrop_filter": raw.get("count", 0),
        "on_screen_count": len(on_screen),
        "total_on_screen_area_px2": sum(e["clippedArea"] for e in on_screen),
        "on_screen": [
            {k: v for k, v in e.items() if k != "zIndex"} for e in on_screen[:25]
        ],
        "off_screen_count": len(els) - len(on_screen),
    }


def scenario_cpu_attribution(ctx, seconds: float = 15.0) -> dict:
    """Attribute idle renderer CPU to a cause, by disabling one thing at a time.

    Nothing is edited on disk: each condition injects a stylesheet through CDP
    and samples CPU, then removes it. The point is to learn *where* the ~98 % of
    a core goes before proposing a change - the particle canvas, the visualizer,
    or the 50 backdrop-filter layers - because only one of those is worth
    optimising and only one of them may be optimisable at all.
    """
    conditions = [
        ("baseline", ""),
        ("no_particles",
         "#particles-bg, #particles-canvas, canvas#particles-bg { display:none !important; }"),
        ("no_visualizer",
         "#visualizer-canvas, .player-visualizer, canvas[data-visualizer] { display:none !important; }"),
        ("no_backdrop_filter",
         "*, *::before, *::after { backdrop-filter:none !important; "
         "-webkit-backdrop-filter:none !important; }"),
        ("no_particles_no_visualizer",
         "#particles-bg, #particles-canvas, #visualizer-canvas, .player-visualizer "
         "{ display:none !important; }"),
    ]

    if getattr(ctx, "spec", {}).get("reverse_conditions"):
        # Position within the session was confounding the result: conditions
        # run later inherited accumulated renderer warm-up, so "hide a canvas"
        # looked like it *cost* CPU. Running the same set backwards separates a
        # causal effect from a positional one - the condition that wins in both
        # orders is real.
        conditions = list(reversed(conditions))

    out = {"seconds_per_condition": seconds, "conditions": {},
           "order": [c[0] for c in conditions]}
    ctx.sampler.start()
    try:
        for label, css in conditions:
            # _summarise() already returns the flat stats dict; don't nest it
            # under "summary", which is what an early version did and which
            # silently broke the comparison script reading these results.
            handle = None
            if css:
                handle = ctx.js(
                    "(() => { let s = document.getElementById('__bench_cond');"
                    " if (!s) { s = document.createElement('style');"
                    " s.id='__bench_cond'; document.head.appendChild(s); }"
                    " s.textContent = %s; return true; })()" % repr(css),
                    timeout=10.0)
            time.sleep(2.0)
            ctx.sampler.samples.clear()
            ctx.sampler._last.clear()
            ctx.sampler._prime()
            perf = _perf_delta(ctx, seconds)
            rows = list(ctx.sampler.samples)
            out["conditions"][label] = _summarise(rows)
            out["conditions"][label]["cdp_delta"] = perf
            out["conditions"][label]["css"] = css or "(none - control)"
            if handle is not None:
                ctx.js("(() => { const s=document.getElementById('__bench_cond');"
                       " if (s) s.textContent=''; return true; })()", timeout=10.0)
    finally:
        ctx.sampler.stop()
    out["backdrop_live"] = scenario_backdrop_live(ctx)
    return out


def scenario_idle_states(ctx, seconds: float = 60.0) -> dict:
    """Idle CPU/RAM in the three states the task names.

    visible+playing, visible+idle, and minimised. The minimised figure is the
    interesting one: it reveals whether the renderer keeps painting when nobody
    can see the window.
    """
    hwnd = find_main_window()
    out = {"hwnd": hwnd, "states": {}}

    def sample(label: str, wait_before: float = 3.0):
        # NB: do not stop the sampler here. An earlier version called
        # stop() inside this helper, which killed the sampling thread and left
        # every state after the first with zero samples - the minimized and
        # restored figures came back empty for exactly that reason.
        time.sleep(wait_before)
        ctx.sampler.samples.clear()
        ctx.sampler._last.clear()
        ctx.sampler._prime()
        time.sleep(seconds)
        rows = list(ctx.sampler.samples)
        out["states"][label] = {
            "summary": _summarise(rows),
            "document_hidden": ctx.js("document.hidden"),
            "visibility_state": ctx.js("document.visibilityState"),
            "n_samples": len(rows),
        }
        return out["states"][label]

    ctx.sampler.start()
    sample("visible_idle")

    # start playback on a real library track so the progress loop is live
    try:
        ctx.js_async("""(async () => {
            const t = await window.pywebview.api.get_library();
            if (t && t.length) { window.__benchTrack = t[0]; }
            return true;
        })()""", timeout=30.0)
    except Exception:
        pass

    # ACTUALLY minimise before sampling, then restore
    set_window_minimized(hwnd, True)
    sample("minimized", wait_before=4.0)
    set_window_minimized(hwnd, False)
    sample("restored", wait_before=3.0)
    ctx.sampler.stop()
    return out


# --------------------------------------------------------------------------
def scenario_startup(ctx) -> dict:
    """Cold-start landmarks.

    ``*_since_nav_ms`` come from the browser's own paint/navigation entries
    (relative to navigationStart). ``app_ready_since_reload_ms`` is wall-clock
    from issuing a reload to the UI reporting itself initialised. The end-to-end
    cold path (interpreter boot + window paint) is ``cold_start.*``, which the
    parent derives from the app's own ``[startup]`` log lines.
    """
    return {
        "python_startup_marker_ms": ctx.startup_markers,
        "fcp_since_nav_ms": ctx.fcp_since_nav_ms,
        "app_ready_since_reload_ms": round(ctx.app_ready_since_reload_ms, 1)
        if ctx.app_ready_since_reload_ms is not None else None,
        "dcl_since_nav_ms": ctx.js(
            "(()=>{const n=performance.getEntriesByType('navigation')[0];"
            "return n?n.domContentLoadedEventEnd:null})()"),
        "load_event_ms": ctx.js(
            "(()=>{const n=performance.getEntriesByType('navigation')[0];"
            "return n?n.loadEventEnd:null})()"),
        "dom_nodes": ctx.js("document.getElementsByTagName('*').length"),
        "js_event_listeners": ctx.js(
            "(()=>{try{return getEventListeners?Object.keys(getEventListeners(window)).length:null}"
            "catch(e){return null}})()"),
        "note": ("app_ready is measured from a warm reload; end-to-end cold "
                 "start is cold_start.* in the parent report"),
    }


# --------------------------------------------------------------------------
def scenario_idle(ctx, seconds: float = 60.0) -> dict:
    """CPU/RAM while the window is visible and idle.

    The sampler runs for the whole window; the first `warmup_sec` seconds are
    dropped so first-paint and asset decode do not pollute the idle figure.
    """
    ctx.sampler.start()
    time.sleep(seconds)
    rows = ctx.sampler.stop()
    return {
        "seconds": seconds,
        "warmup_sec": ctx.warmup_sec,
        "summary": ctx.sampler.summary(warmup=ctx.warmup_sec),
        "perf": ctx.perf_metrics(),
    }


# --------------------------------------------------------------------------
SCROLL_JS = r"""
(async (sel, frames) => {
  const el = document.querySelector(sel);
  if (!el) return { error: 'selector not found: ' + sel };
  const times = [];
  let last = performance.now();
  let stop = false;
  function tick(now) {
    times.push(now - last);
    last = now;
    if (!stop) requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
  // programmatic scroll: 120 frames down, then 120 back up
  const startTop = el.scrollTop;
  const step = Math.max(20, (el.scrollHeight - el.clientHeight) / 120);
  for (let i = 0; i < 120; i++) {
    el.scrollTop = startTop + step * i;
    await new Promise(r => requestAnimationFrame(r));
  }
  for (let i = 120; i >= 0; i--) {
    el.scrollTop = startTop + step * i;
    await new Promise(r => requestAnimationFrame(r));
  }
  await new Promise(r => requestAnimationFrame(r));
  stop = true;
  const d = times.slice(2);
  d.sort((a, b) => a - b);
  const mean = d.reduce((a, b) => a + b, 0) / d.length;
  return {
    frames: d.length,
    meanFrameMs: +mean.toFixed(2),
    medianFrameMs: +d[Math.floor(d.length / 2)].toFixed(2),
    p95FrameMs: +d[Math.floor(d.length * 0.95)].toFixed(2),
    worstFrameMs: +d[d.length - 1].toFixed(2),
    longFramesOver50ms: d.filter(x => x > 50).length,
    derivedFps: +(1000 / mean).toFixed(1),
    scrollHeight: el.scrollHeight,
    clientHeight: el.clientHeight,
  };
})
"""


def scenario_scroll(ctx, selector: str, label: str, rounds: int = 3) -> dict:
    """Scroll FPS over a long list. Median of `rounds` passes per call."""
    runs = []
    for _ in range(rounds):
        res = ctx.js_async(SCROLL_JS.replace("async (sel, frames)", "async (sel)")
                           .replace("(sel, frames)", "(sel)"),
                           args_fmt=f"({selector!r})")
        if not res or res.get("error"):
            return {"label": label, "selector": selector, "error": res.get("error") if res else "null result"}
        runs.append(res)
    return {
        "label": label,
        "selector": selector,
        "rounds": rounds,
        "medianFrameMs": round(statistics.median(r["medianFrameMs"] for r in runs), 2),
        "medianDerivedFps": round(statistics.median(r["derivedFps"] for r in runs), 1),
        "p95FrameMs_worst": round(max(r["p95FrameMs"] for r in runs), 2),
        "worstFrameMs_worst": round(max(r["worstFrameMs"] for r in runs), 2),
        "longFramesOver50ms_total": sum(r["longFramesOver50ms"] for r in runs),
        "rows_rendered": runs[0].get("scrollHeight"),
        "runs": runs,
    }


# --------------------------------------------------------------------------
SEARCH_JS = r"""
(async (query) => {
  const seen = [];
  const t0 = performance.now();
  const done = new Promise(resolve => {
    const handler = (name, payload) => {
      const t = performance.now() - t0;
      seen.push({ name, t });
      if (name === 'search_completed') {
        window.pywebview._removeEventListener?.('search_completed', handler);
        resolve(t);
      }
    };
    window.pywebview.api.__benchHook = handler;
    // route through the normal path so we measure the real user flow
    const orig = window.onPythonEvent;
    if (!window.__benchOriginalEmit) {
      window.__benchOriginalEmit = orig;
      window.onPythonEvent = function (name, payload) {
        try { window.pywebview.api.__benchHook && window.pywebview.api.__benchHook(name, payload); } catch (e) {}
        return window.__benchOriginalEmit.apply(this, arguments);
      };
    }
    window.pywebview.api.search(query, 'all');
  });
  const t = await Promise.race([done, new Promise(r => setTimeout(() => r(-1), 20000))]);
  return {
    query, completedAfterMs: t, events: seen,
    resultCards: document.querySelectorAll('#search-results .track-item, #search-results .result-item').length,
  };
})
"""


def scenario_search(ctx, query: str = "Daft Punk", rounds: int = 3) -> dict:
    """Time from issuing the bridge search call to `search_completed`."""
    runs = []
    for _ in range(rounds):
        res = ctx.js_async(SEARCH_JS, args_fmt=f"({query!r})")
        if res:
            runs.append(res)
    if not runs:
        return {"error": "no search result"}
    ok = [r for r in runs if r.get("completedAfterMs", -1) >= 0]
    return {
        "query": query,
        "rounds": rounds,
        "medianMs": round(statistics.median(r["completedAfterMs"] for r in ok), 1) if ok else None,
        "runs": runs,
    }


# --------------------------------------------------------------------------
def scenario_feed(ctx) -> dict:
    """Home-feed build time + Last.fm request count for one build."""
    return ctx.measure_feed()
