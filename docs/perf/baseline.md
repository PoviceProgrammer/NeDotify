# NeDotify — baseline performance, Phase 0

Date: 2026-10-04 · Branch: `fix/audit-2026-10-03` · HEAD at capture: `62eff6c`
Machine: Windows, WebView2 154.0.4258.53, Python 3.14.7 (`.venv_win`)

All numbers are **medians over N repetitions** unless stated. Every run used a
scratch profile (`USERPROFILE` redirected) with a fixed 2000-track fixture, so
the real `~/.nedotify` was never touched.

## 0. What was measured, and what was not

Measured on the real application, launched as a real subprocess, driven through
the Chrome DevTools Protocol:

| Metric | Value | N | Source |
|---|---|---|---|
Cold start → window loaded | **2035 ms** | 5 | `startup-2000trk-*.json` |
— interpreter + module imports | 446 ms | 5 | `cold_start.interpreter_and_import_ms` |
— `AppCore()` construction | 34 ms | 5 | `[startup] AppCore initialized` |
— first paint (FCP, warm reload) | 136 ms | 5 | `child.data.fcp_since_nav_ms` |
— interactive (warm reload) | 523 ms | 5 | `child.data.app_ready_since_reload_ms` |
Scroll FPS, 2000-track library | 16.7 ms/frame (≈60 FPS) | 3 | `combo-*.json` |
Search → results | 8298 ms | 3 | `combo-*.json` |
Idle CPU, window visible | see §3 | 3–5 | `idle-*.json`, `idle_states-*.json` |
Idle CPU, window minimised | **10.6 %** of a core | 3 | `idle_states-*.json` |
RAM (Python + WebView2) | 711–755 MB | 3–5 | `tree_rss_mb` |

**Not measured** (stated plainly, not estimated):

- RAM after a full 10-minute playback run — only a short idle window was run.
- Playback of real audio (no stream resolved in the hermetic fixture), so
  decode cost is absent from every figure above.
- Seek/scrub latency and application close time.
- `dist/` size, onefile unpack time, onefile vs onedir.
- Golden screenshots and the visual-guard comparison (deferred at owner's request).

## 1. Method notes worth keeping

Four harness bugs were found and fixed; each had produced a wrong number first.

1. **`WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS` is ignored.** pywebview assigns
   `props.AdditionalBrowserArguments` itself
   (`webview/platforms/edgechromium.py:48`), and once `CreationProperties`
   carries that property WebView2 disregards the environment variable. The port
   never opened. The supported switch is
   `webview.settings["REMOTE_DEBUGGING_PORT"]`.
2. **Polling after `Page.reload` read the outgoing document.** `window._nedotifyInitialized`
   was still `true` there, so "time to interactive" reported 0.4 ms and later
   139 ms for a ~2 s boot. Fixed by waiting for `performance.timeOrigin` to change.
3. **The process sampler reported 0.00 % CPU on a busy process.** psutil's
   `cpu_percent(interval=None)` depends on per-`Process` internal caching that
   `oneshot()` can recycle. Replaced with a self-held differencing of
   `cpu_times()`. Verified against two spinning threads: 0.00 % → **100.25 %**.
   *Every idle CPU number taken before this fix was fiction.*
4. **The onboarding wizard covered the entire window during every benchmark.**
   `SettingsManager` coerces only the literals `"true"`/`"false"`
   (`core/settings.py:361`); the fixture wrote `"1"`, which returns `int 1`,
   and `js/onboarding.js:30` tests `first_launch_done === true`. The wizard then
   rendered full-screen — 825 000 px² of extra `backdrop-filter`. Found by a
   live computed-style audit, not by reading CSS.

## 2. Rejected optimisations (measured, then discarded)

| Candidate | Claimed | Measured | Verdict |
|---|---|---|---|
Make `SpotifyService` lazy | 81 ms off startup | **12.3 ms (2.7 %)**, sample sets overlap | **rejected** |
Delete unused `VKService` | 103 ms | ≈0 ms | **rejected** |

- *Spotify*: the theory was that it is the first module to `import requests`.
  It is — but `yt_dlp.networking._requests` imports `requests` immediately
  afterwards anyway, so the cost is merely relocated. Interleaved A/B, n=9 per
  arm: eager median 457 ms vs lazy 445 ms.
- *VKService*: assigned at `core/app.py:121` and never read anywhere. But
  `yt_dlp` is imported at module level by `playlist_import_service`,
  `vk_service` **and** `youtube_service`, and YouTube is constructed eagerly, so
  removing VK just shifts 151 ms onto YouTube. The static profile credits
  whichever module happens to import first, which is misleading.
- Per the 5 % rule, a 2.7 % gain inside the noise is not committed.

## 3. Idle CPU — measured, with an unresolved question

`document.hidden` **does** become `true` on minimise, and the existing
visibility guards work: renderer CPU falls from ~102 % to ~2.8 % of a core.
So "pause on minimise" is already implemented and is not an opportunity.

What is *not* explained yet: with the window **visible and idle**, the renderer
sustains a high CPU figure, and the runs disagree with each other
(47 %, 91 %, 111 %, 119 % of a core across runs). Two attributions were
measured, each with a control and one run in reversed order to cancel
positional drift:

| Condition | renderer CPU | Δ |
|---|---|---|
baseline | 91.7 % | — |
`backdrop-filter: none` everywhere | 62.1 % | **−29.6 pts (−32 %)** |
particles canvas hidden | 91.7 % | 0.0 |
visualizer canvas hidden | 100.1 % | +9.2 (noise) |

Disabling `backdrop-filter` is the only condition that reproduced in both
orders. The canvas results are not distinguishable from noise — `display:none`
forces a relayout, which confounds the measurement.

CDP counters over a 20 s idle window show **zero layouts, zero style
recalcs**, and only 0.18 s of script. So the idle cost is not JavaScript and
not layout: it is raster/composite work, consistent with backdrop surfaces being
re-sampled. That points at continuous repaint sources (14 `infinite` CSS
animations were counted statically), but that link is **not yet proven**.

Only three elements actually paint a backdrop-filter in the default theme:

| element | on-screen area | blur | own background |
|---|---|---|---|
`#main-content` | 536 784 px² | 14 px | `color-mix(... 75 %)` → ~0.56 alpha |
`#sidebar` | 126 600 px² | 14 px + saturate(1.8) | ~0 alpha |
`#player-bar` | 87 024 px² | 16 px | translucent |

All three are genuinely translucent, so their blur is visible and removing it
would change the appearance — **not permitted**. Note also that the static
ranking's top entry, `#main-content` as a full-bleed backdrop-filter root, only
holds under `html.has-custom-bg` (`base.css:372`); in the default theme it has
no blur at all.

## 4. Frontend static findings (from `prof_frontend.md`)

- **76 000 DOM nodes** for a 2000-track library, no virtualization
  (38 nodes/row, derived from the real template and the real lucide icon map).
- One synchronous turn can build **1 050 rows / ~39 900 nodes / 7 350
  listeners** before the browser paints (`library.js:372` batch 50, `:403`
  drains 20 more).
- `initParticles()` leaks 4 `window` listeners per call and is driven by
  unthrottled slider `input` handlers (`particles.js:263-305`).
- Rank-3 hot spot lies inside the owner's in-flight `lyrics.js` — reported, not
  touched.

## 5. Reproducing

```
python tools/bench/run_bench.py --scenario startup       --reps 5 --tracks 2000
python tools/bench/run_bench.py --scenario idle          --reps 3 --seconds 60
python tools/bench/run_bench.py --scenario idle_states   --reps 3 --seconds 30
python tools/bench/run_bench.py --scenario cpu_attribution --reps 5 --seconds 15
python -m pytest -q            # 574 passed, 3 xfailed
```

Requires the app to be closed: NeDotify holds
`Local\NeDotify_App_Single_Instance_Mutex`, and a second launch exits silently.
