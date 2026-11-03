"""Runs INSIDE the NeDotify process as part of a benchmark run.

pywebview requires ``webview.start()`` on the main thread, so this module keeps
the main thread free for the real app and does all measuring on a worker
thread over the Chrome DevTools Protocol. It never modifies app behaviour: it
only reads timings out of the renderer and wraps one Last.fm method with a
counter.

Selected by the parent through ``$NEDOTIFY_BENCH_SPEC`` (a JSON file).
"""

from __future__ import annotations

import json
import os
import statistics
import sys
import threading
import time
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from tools.bench import cdp, procsampler, scenarios  # noqa: E402

SPEC_PATH = os.environ.get("NEDOTIFY_BENCH_SPEC")
RESULTS_PATH = os.environ.get("NEDOTIFY_BENCH_RESULTS")
DEBUG_PORT = int(os.environ.get("NEDOTIFY_BENCH_PORT", "9222"))
MODE = os.environ.get("NEDOTIFY_BENCH_MODE", "bench")

# init entry is not readiness: await the event emitted after module init and
# restored-session acknowledgement. Installed before reload to avoid races.
READY_HOOK_JS = """
window.__benchAppReady = false;
window.addEventListener('nedotify:app_ready', () => {
    window.__benchAppReady = true;
    window.__benchAppReadyMs = performance.now();
}, {once: true});
"""


def _dump(payload: dict) -> None:
    if not RESULTS_PATH:
        return
    p = Path(RESULTS_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


class BenchContext:
    def __init__(self, spec: dict):
        self.spec = spec
        self.sampler = procsampler.ProcSampler(interval=spec.get("sample_interval", 1.0))
        self.warmup_sec = spec.get("warmup_sec", 5.0)
        self.startup_markers: dict = {}
        self.app_ready_ms = None
        self.bridge_ready_ms = None
        self.sess: cdp.CDPSession | None = None
        self.app_ready_since_reload_ms = None
        self.bridge_ready_since_reload_ms = None
        self.fcp_since_nav_ms = None
        self.profile_root = Path(spec["profile_root"])
        self.log: list[str] = []

    # -- renderer helpers --------------------------------------------------
    def js(self, expr: str, timeout: float = 15.0):
        return self.sess.js(expr, timeout=timeout)

    def js_async(self, expr: str, args_fmt: str = "", timeout: float = 60.0):
        call = f"({expr})({args_fmt})" if args_fmt else f"({expr})()"
        return self.sess.js(call, timeout=timeout, await_promise=True)

    def perf_metrics(self) -> dict:
        try:
            return self.sess.perf_metrics()
        except Exception:
            return {}

    def js_first_paint(self) -> float | None:
        try:
            return self.js(
                "(()=>{const e=performance.getEntriesByType('paint')"
                ".find(p=>p.name==='first-contentful-paint');"
                "return e?e.startTime:null})()")
        except Exception:
            return None

    # -- startup markers ---------------------------------------------------
    def read_startup_markers(self) -> dict:
        """Parse `[startup] ... (+Nms)` lines out of the app log."""
        log_file = self.profile_root / ".nedotify" / "logs" / "app.log"
        out: dict[str, float] = {}
        if not log_file.exists():
            return out
        try:
            text = log_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return out
        for line in text.splitlines():
            if "[startup]" not in line or "(+" not in line:
                continue
            try:
                msg = line.split("INFO: ", 1)[-1]
                label = msg.split("(+", 1)[0].replace("[startup] ", "").strip()
                ms = float(msg.split("(+", 1)[1].split("ms)", 1)[0])
                out[label] = ms
            except (IndexError, ValueError):
                continue
        return out

    # -- Last.fm request counting -----------------------------------------
    def measure_feed(self) -> dict:
        """Time the home feed with deterministic, provider-free API fixtures."""
        t0 = time.monotonic()
        self.js_async(
            """(async () => {
                 window.showPage('home');
                 await new Promise(r => setTimeout(r, 50));
                 const a = window.pywebview.api;
                 a.get_popular_tracks('US');
                 a.get_feed(20);
                 a.get_home_releases(10);
                 a.get_home_mixes(10);
                 return true;
               })()""", timeout=30.0)
        deadline = time.monotonic() + 10.0
        expected = ["feed_ready", "popular_results", "releases_ready", "mixes_ready"]
        while time.monotonic() < deadline:
            count = self.js(
                "(window.__bench && window.__bench.pythonEvents || [])"
                ".filter(e => %s.indexOf(e.name) >= 0).length" % json.dumps(expected))
            if count >= len(expected):
                break
            time.sleep(0.05)
        elapsed = time.monotonic() - t0
        return {
            "wall_ms": round(elapsed * 1000, 1),
            "provider_requests": 0,
            "fixture": "deterministic seeded local bridge payloads",
        }


def _run_capture(ctx: BenchContext, spec: dict) -> dict:
    """Visual-guard capture mode.

    localStorage must be in place *before* ``js/main.js`` runs its synchronous
    ``restorePreferences()``, so we inject it with
    ``Page.addScriptToEvaluateOnNewDocument`` and reload. Seeding it after load
    would race the first paint and make the golden depend on timing.
    """
    from pathlib import Path as _P

    from tools.visual_guard import capture as vg_capture
    from tools.visual_guard import fixtures as vg_fixtures

    theme_name = spec.get("theme", "dark")
    theme = vg_fixtures.THEMES[theme_name]
    out_dir = _P(spec["out_dir"])

    origin_before = ctx.sess.js("performance.timeOrigin")
    ctx.sess.ws.call("Page.addScriptToEvaluateOnNewDocument", {
        "source": READY_HOOK_JS + vg_fixtures.localstorage_seed_script(theme)})
    ctx.sess.ws.call("Network.enable")
    ctx.sess.ws.call("Network.setCacheDisabled", {"cacheDisabled": True})
    ctx.sess.ws.call("Page.reload", {"ignoreCache": True})
    print("[bench] reloaded with seeded localStorage", flush=True)

    ctx.sess.wait_for_new_document(origin_before, timeout=90.0)
    ctx.sess.wait_for_js("window.__benchAppReady === true", timeout=90.0)
    print("[bench] app re-ready after reload", flush=True)
    time.sleep(spec.get("settle_sec", 2.0))

    recs = vg_capture.capture_theme(
        ctx.sess, out_dir, theme_name,
        spec.get("screens", vg_fixtures.ALL_SCREENS),
        [tuple(v) for v in spec.get("viewports", vg_fixtures.VIEWPORTS)],
        spec.get("dprs", vg_fixtures.DPRS))

    bad = [r for r in recs if r["driver_error"]]
    ctx_capture = {"captured": len(recs), "driver_errors": bad}
    return {"ok": not bad, "error": None if not bad else f"{len(bad)} screens failed",
            "data": ctx_capture}


def driver() -> None:
    spec = json.loads(Path(SPEC_PATH).read_text(encoding="utf-8"))
    ctx = BenchContext(spec)
    result = {
        "scenario": spec.get("scenario", "startup"),
        "mode": MODE,
        "started_at": time.time(),
        "ok": False,
        "error": None,
        "data": {},
    }

    def finish() -> None:
        result["finished_at"] = time.time()
        _dump(result)

    try:
        print("[bench] waiting for CDP target...", flush=True)
        if os.environ.get('NEDOTIFY_BENCH_TRANSPORT') == 'native':
            ctx.sess = cdp.CDPSession.attach_native(timeout=90.0)
        else:
            ctx.sess = cdp.CDPSession.attach(port=DEBUG_PORT, timeout=90.0,
                                              url_filter=spec.get("url_filter"))
        print("[bench] CDP attached", flush=True)
        if MODE == "capture":
            ctx.sess.install_event_recorder()
            result.update(_run_capture(ctx, spec))
            return

        # "Time to interactive": reload, then time until the *new* document is
        # interactive. Two ordering hazards, both hit during development:
        #   1. polling right after Page.reload reads the OUTGOING document, where
        #      _nedotifyInitialized is still true -> reported 139 ms for a 2 s boot
        #   2. so wait for performance.timeOrigin to change before polling at all
        try:
            origin_before = ctx.sess.js("performance.timeOrigin", timeout=5.0)
            t_reload = time.monotonic()
            ctx.sess.ws.call("Page.addScriptToEvaluateOnNewDocument",
                             {"source": READY_HOOK_JS})
            ctx.sess.ws.call("Page.reload", {"ignoreCache": False})
            ctx.sess.wait_for_new_document(origin_before, timeout=90.0)
            t_new_doc = time.monotonic()
            ctx.sess.wait_for_js("window.__benchAppReady === true",
                                 timeout=90.0)
            # Page.reload replaces the JS context, so instrumentation must be
            # installed into the committed document used by the scenarios.
            ctx.sess.install_event_recorder()
            ctx.app_ready_since_reload_ms = (time.monotonic() - t_reload) * 1000.0
            ctx.new_document_committed_ms = (t_new_doc - t_reload) * 1000.0
            ctx.fcp_since_nav_ms = ctx.sess.js(
                "(()=>{const e=performance.getEntriesByType('paint')"
                ".find(p=>p.name==='first-contentful-paint');"
                "return e?e.startTime:null})()")
            print(f"[bench] new doc committed at +{ctx.new_document_committed_ms:.0f}ms, "
                  f"interactive at +{ctx.app_ready_since_reload_ms:.0f}ms "
                  f"(FCP {ctx.fcp_since_nav_ms}ms since navStart)", flush=True)
        except Exception as exc:
            print(f"[bench] ready measurement failed: {exc}", flush=True)

        # The renderer signals readiness itself, so this measures the real
        # end-to-end startup rather than the harness noticing late.
        ctx.app_ready_ms = ctx.sess.wait_for_js(
            "window.__benchAppReady === true", timeout=90.0) * 1000.0
        ctx.bridge_ready_ms = ctx.sess.wait_for_js(
            "!!(window.pywebview && window.pywebview.api && "
            "typeof window.pywebview.api.get_settings === 'function')",
            timeout=90.0) * 1000.0
        print(f"[bench] app_ready at +{ctx.app_ready_ms:.0f}ms", flush=True)

        ctx.startup_markers = ctx.read_startup_markers()
        time.sleep(spec.get("settle_sec", 2.0))

        name = spec.get("scenario", "startup")
        if name == "startup":
            result["data"] = scenarios.scenario_startup(ctx)
        elif name == "idle":
            result["data"] = scenarios.scenario_idle(ctx, spec.get("seconds", 60.0))
        elif name == "idle_states":
            result["data"] = scenarios.scenario_idle_states(
                ctx, spec.get("seconds", 60.0))
        elif name == "cpu_attribution":
            result["data"] = scenarios.scenario_cpu_attribution(
                ctx, spec.get("seconds", 15.0))
        elif name == "scroll":
            result["data"] = [scenarios.scenario_scroll(ctx, sel, label,
                                                        spec.get("rounds", 3))
                              for sel, label in spec.get("targets", [])]
        elif name == "search":
            result["data"] = scenarios.scenario_search(ctx, spec.get("query", "Daft Punk"),
                                                       spec.get("rounds", 3))
        elif name == "feed":
            result["data"] = scenarios.scenario_feed(ctx)
        elif name == "audio":
            result["data"] = scenarios.scenario_audio(ctx)
        elif name == "play":
            result["data"] = scenarios.scenario_play(ctx)
        elif name == "download":
            result["data"] = scenarios.scenario_download(ctx)
        elif name == "combo":
            out = {}
            out["startup"] = scenarios.scenario_startup(ctx)
            out["feed"] = scenarios.scenario_feed(ctx)
            out["play"] = scenarios.scenario_play(ctx)
            out["download"] = scenarios.scenario_download(ctx)
            out["scroll"] = [scenarios.scenario_scroll(ctx, sel, label,
                                                       spec.get("rounds", 3))
                             for sel, label in spec.get("targets", [])]
            out["search"] = scenarios.scenario_search(ctx, spec.get("query", "Daft Punk"),
                                                      spec.get("rounds", 3))
            out["idle"] = scenarios.scenario_idle(ctx, spec.get("seconds", 60.0))
            out["perf_at_end"] = ctx.perf_metrics()
            result["data"] = out
        else:
            result["error"] = f"unknown scenario {name!r}"

        errors=scenarios.scenario_errors(result["data"])
        if errors:result["error"]="; ".join(errors)
        result["ok"] = result["error"] is None
        result["perf"] = ctx.perf_metrics()
    except Exception:
        result["error"] = traceback.format_exc()
        traceback.print_exc()
    finally:
        finish()
        # close the app so the parent can time process exit
        time.sleep(spec.get("pre_close_sec", 0.2))
        try:
            import webview
            t = time.monotonic()
            for w in list(webview.windows):
                w.destroy()
            print(f"[bench] destroy issued at +{time.monotonic()-t:.3f}s", flush=True)
        except Exception:
            traceback.print_exc()


def main() -> None:
    if not SPEC_PATH:
        print("[bench] no spec; running the app normally", flush=True)
        import main as app_main
        app_main.main()
        return

    # CDP hook. WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS alone is NOT enough:
    # pywebview assigns props.AdditionalBrowserArguments itself
    # (webview/platforms/edgechromium.py:48), and once CreationProperties carries
    # AdditionalBrowserArguments the WebView2 runtime ignores the environment
    # variable. Measured: with the real app the env var left :9222 closed. The
    # supported switch is webview.settings['REMOTE_DEBUGGING_PORT'], which
    # pywebview appends to those arguments. Bench-only, no app code touched.
    try:
        import webview
        webview.settings["REMOTE_DEBUGGING_PORT"] = DEBUG_PORT
    except Exception:
        traceback.print_exc()

    if MODE in {"bench", "capture"}:
        # Provider paths are replaced only in this isolated child process.
        # UI scenarios still call the bridge and observe its normal events.
        from core.api import AppApi
        from tools.bench.api_stubs import install_benchmark_api_stubs
        install_benchmark_api_stubs(AppApi, os.environ.get("NEDOTIFY_BENCH_PROFILE", "."))
        if MODE == "capture":
            from tools.visual_guard.fixtures import LYRICS_PAYLOAD

            def capture_lyrics(self, track_name, artist_name, duration_ms=0,
                               file_path=None, album_name='', request_id=None):
                return dict(LYRICS_PAYLOAD, track_name=track_name,
                            artist_name=artist_name, request_id=request_id)

            AppApi.get_lyrics = capture_lyrics

    threading.Thread(target=driver, name="BenchDriver", daemon=True).start()
    import main as app_main
    app_main.main()
    # main() returned => window closed; flush any partial result
    print("[bench] app main() returned", flush=True)


if __name__ == "__main__":
    main()
