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
        """One home-feed build: wall time + exact count of Last.fm HTTP calls.

        Counting at ``_api_request`` would under-report: with no API key
        configured it short-circuits at line ~315 and never reaches the socket
        at line 330, so every count would be zero while the call tree was still
        being walked. Instead we install a dummy key and swap the per-thread
        ``requests.Session`` for a fake whose ``get`` records the call and
        returns an empty-but-valid Last.fm payload.

        The number is therefore the real outbound request count, obtained
        without a single packet leaving the machine.
        """
        from services.lastfm_service import LastFMService

        calls: list[dict] = []

        class _FakeResponse:
            status_code = 200
            text = ""
            headers: dict = {}

            @staticmethod
            def json():
                # Valid but empty: exercises the same code path a real
                # response would without inventing chart/artist data.
                return {"results": {}}

        class _FakeSession:
            def get(self, url, params=None, timeout=None, **kw):
                calls.append({"method": (params or {}).get("method"),
                              "t": time.monotonic()})
                return _FakeResponse()

            def close(self):
                pass

        orig_session = LastFMService._get_session
        orig_keys = list(getattr(LastFMService, "API_KEYS", []))

        def fake_session(self_svc):
            return _FakeSession()

        LastFMService._get_session = fake_session
        LastFMService.API_KEYS = ["bench-dummy-key"]
        try:
            import os as _os
            _os.environ["LASTFM_API_KEY"] = "bench-dummy-key"
            # force the availability check to pass on a fresh instance
            orig_available = LastFMService.available.fget if isinstance(
                getattr(LastFMService, "available", None), property) else None

            def force_available(self_svc):
                return True

            if orig_available is not None:
                LastFMService.available = property(force_available)
        except Exception:
            traceback.print_exc()

        try:
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
            # Wait for the async feed results to arrive. The bridge reports
            # feed completion through window.onPythonEvent names; the recorder
            # installed at startup collects them into window.__bench.
            deadline = time.monotonic() + 25.0
            feed_events = ("authentic_home_ready", "feed_ready", "popular_results",
                           "releases_ready", "mixes_ready")
            settle_deadline = time.monotonic() + 3.0
            seen = -1
            stable_since = None
            while time.monotonic() < deadline:
                got = self.js(
                    "(window.__bench && window.__bench.pythonEvents || [])"
                    ".filter(e => %s.indexOf(e.name) >= 0).length"
                    % json.dumps(list(feed_events)))
                if got != seen:
                    seen = got
                    stable_since = time.monotonic()
                # stop when the event count has stopped growing AND the
                # provider pools have had time to issue any trailing requests
                if (stable_since is not None
                        and time.monotonic() - stable_since > 1.0
                        and time.monotonic() > settle_deadline):
                    break
                time.sleep(0.1)
            time.sleep(2.0)          # let the provider pools drain
            elapsed = time.monotonic() - t0
        finally:
            LastFMService._get_session = orig_session
            LastFMService.API_KEYS = orig_keys
            if orig_available is not None:
                LastFMService.available = orig_available
            _os.environ.pop("LASTFM_API_KEY", None)

        return {
            "wall_ms": round(elapsed * 1000, 1),
            "lastfm_requests": len(calls),
            "lastfm_methods": [c["method"] for c in calls],
            "unique_methods": sorted({str(c["method"]) for c in calls}),
            "duplicate_methods": len(calls) - len({c["method"] for c in calls}),
            "note": ("outbound HTTP call count, measured with a dummy key and a "
                     "fake session so nothing leaves the machine"),
        }


# Injected BEFORE any page script so it can observe the moment the UI becomes
# interactive. Measuring it from the driver thread is useless: by the time CDP
# attaches the app has long finished booting, which is why an earlier version
# reported a nonsensical "app_ready = 2.57 ms".
READY_HOOK_JS = """
(function () {
  if (window.__benchHookInstalled) return;
  window.__benchHookInstalled = true;
  window.__benchReadyMs = null;
  try {
    document.addEventListener('nedotify:app_ready', function () {
      if (window.__benchReadyMs === null) window.__benchReadyMs = performance.now();
    }, true);
  } catch (e) {}
  var iv = setInterval(function () {
    if (window._nedotifyInitialized === true) {
      if (window.__benchReadyMs === null) window.__benchReadyMs = performance.now();
      clearInterval(iv);
    }
  }, 10);
})();
"""


def _run_capture(ctx: BenchContext, spec: dict) -> None:
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

    ctx.sess.ws.call("Page.addScriptToEvaluateOnNewDocument", {
        "source": vg_fixtures.localstorage_seed_script(theme)})
    ctx.sess.ws.call("Network.enable")
    ctx.sess.ws.call("Network.setCacheDisabled", {"cacheDisabled": True})
    ctx.sess.ws.call("Page.reload", {"ignoreCache": True})
    print("[bench] reloaded with seeded localStorage", flush=True)

    ctx.sess.wait_for_js("window._nedotifyInitialized === true", timeout=90.0)
    print("[bench] app re-ready after reload", flush=True)
    time.sleep(spec.get("settle_sec", 2.0))

    recs = vg_capture.capture_theme(
        ctx.sess, out_dir, theme_name,
        spec.get("screens", vg_fixtures.ALL_SCREENS),
        [tuple(v) for v in spec.get("viewports", vg_fixtures.VIEWPORTS)],
        spec.get("dprs", vg_fixtures.DPRS))

    bad = [r for r in recs if r["driver_error"]]
    ctx_capture = {"captured": len(recs), "driver_errors": bad}
    _dump({"ok": not bad, "error": None if not bad else f"{len(bad)} screens failed",
           "data": ctx_capture})


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
        ctx.sess = cdp.CDPSession.attach(port=DEBUG_PORT, timeout=90.0,
                                          url_filter=spec.get("url_filter"))
        print("[bench] CDP attached", flush=True)
        ctx.sess.install_event_recorder()

        if MODE == "capture":
            _run_capture(ctx, spec)
            result["ok"] = result["error"] is None
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
            ctx.sess.wait_for_js("window._nedotifyInitialized === true",
                                 timeout=90.0)
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
            "window._nedotifyInitialized === true", timeout=90.0) * 1000.0
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
        elif name == "combo":
            out = {}
            out["startup"] = scenarios.scenario_startup(ctx)
            out["feed"] = scenarios.scenario_feed(ctx)
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

    threading.Thread(target=driver, name="BenchDriver", daemon=True).start()
    import main as app_main
    app_main.main()
    # main() returned => window closed; flush any partial result
    print("[bench] app main() returned", flush=True)


if __name__ == "__main__":
    main()
