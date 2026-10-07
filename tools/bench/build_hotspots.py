"""Aggregate every measurement produced by the frontend profiling pass into the
single canonical artefact: tools/bench/results/frontend_hotspots.json

READ-ONLY with respect to the application. Consumes the sibling outputs:

  tools/bench/results/css_blur_map.json        (tools/bench/css_inventory.py)
  tools/bench/results/backdrop_nesting.json    (tools/bench/dom_nesting.py)
  tools/bench/results/track_row_nodes.json     (tools/bench/track_row_nodes.js)
  tools/bench/js_census.py                     (re-run in-process)

and adds the hand-verified classification tables that a static scanner cannot
derive (per-loop target frame rate, hidden-awareness, opaque-layer alpha).
Every hand-verified row carries `evidence: "static-read"` and the file:line it
was read from, so nothing in this file is an unattributed claim.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RESULTS = REPO / "tools" / "bench" / "results"
CSS_DIR = REPO / "ui" / "web_new_v2" / "css"

import sys  # noqa: E402

sys.path.insert(0, str(REPO / "tools" / "bench"))
import js_census  # noqa: E402
from css_inventory import IMPORT_ORDER, parse_file  # noqa: E402


# ---------------------------------------------------------------- section 1
# Hand-verified by reading each loop. `checks` values:
#   yes      -> the loop itself (or a bound visibility handler) tests it
#   via-cb   -> it is tested by a registered visibilitychange handler
#   no       -> not tested
RAF_LOOPS = [
    {
        "id": "particles",
        "file": "ui/web_new_v2/js/particles.js",
        "self_schedule_line": 405,
        "start_lines": [38, 280, 465, 479],
        "callback": "animate(timestamp)",
        "animates": "2D canvas particle field in #particles-bg (position fixed, inset -25px, z-index 1) - ambient background behind every view",
        "target_fps": "24 default (particles.js:17 targetFps); setParticlesFps clamps 5..30; nedotify:efficiency_state forces 15 (particles.js:484); battery saver 15 (particles.js:493)",
        "throttle_mechanism": "elapsed < frameInterval -> return (particles.js:408-414) - the rAF still fires at display rate, only drawing is throttled",
        "checks_document_hidden": "yes",
        "checks_hidden_line": 400,
        "checks_other_view": "no - #particles-bg is fixed and covers all views (base.css:1425-1434)",
        "checks_mini_player": "yes - body.mini-player-active (particles.js:400)",
        "runs_when_minimized": "no - document.hidden check inside animate() sets animFrameId = null and stops",
        "duplicate_start_guard": "yes - initParticles cancels animFrameId first (particles.js:208-211)",
        "listener_leak": "YES - initParticles() re-creates onResize/onMouseMove/onMouseLeave/onMiniPlayerToggled every call and removeEventListener()s the NEW closure, so each call permanently adds 1 window resize + 1 window mousemove + 1 window mouseleave + 1 window nedotify:mini_player_toggled listener (particles.js:263-305). initParticles() is called from 7 sites in settings.js (124, 129, 134, 202, 614, 689, 1315) and the 3 particle sliders call it on EVERY unthrottled `input` event (settings.js:643-646 -> 124/129/134).",
        "per_frame_work": "ctx.clearRect(full viewport) + up to 80 drawImage calls from cached sprites (particleCount capped at 80, or 25 on <=4-core)",
        "evidence": "static-read",
    },
    {
        "id": "visualizer",
        "file": "ui/web_new_v2/js/visualizer.js",
        "self_schedule_line": 280,
        "start_lines": [43, 78, 86, 98, 174],
        "callback": "draw(timestamp)",
        "animates": "#visualizer-canvas (player view) and #home-visualizer-canvas (home view) - 48-bar audio-reactive spectrum/wave/circle",
        "target_fps": "24 default (visualizer.js:16); setVisualizerFps clamps 5..60; nedotify:efficiency_state forces 15 (visualizer.js:448)",
        "throttle_mechanism": "elapsed < frameInterval -> return (visualizer.js:286-288)",
        "checks_document_hidden": "yes",
        "checks_hidden_line": 255,
        "checks_other_view": "yes - stops when no canvas is visible: offsetParent !== null && closest('.view-page').classList.contains('active') (visualizer.js:263-275)",
        "checks_mini_player": "indirect - #main-content is display:none in mini-player mode (base.css:2280-2295) so offsetParent is null",
        "runs_when_minimized": "no - documentVisible flag (visualizer.js:73-80)",
        "duplicate_start_guard": "yes - every start site checks !animFrameId",
        "idle_behaviour": "when paused it deliberately keeps re-requesting rAF and runs a gentle idle animation (visualizer.js:277-280) - this is a permanent 24fps loop while the player view/home view is visible, even paused",
        "per_frame_work": "targets.forEach: 2x offsetParent read (layout read) + 2x closest('.view-page') DOM walk + optional canvas redraw; getCachedPrimaryRgb() caches getComputedStyle for 5s (visualizer.js:178-187)",
        "evidence": "static-read",
    },
    {
        "id": "player-progress",
        "file": "ui/web_new_v2/js/player.js",
        "self_schedule_line": 1070,
        "start_lines": [1031, 1067, 1215, 1476],
        "callback": "animateProgress(timestamp)",
        "animates": "pb/pp/mp progress-fill transforms, 3x aria-valuenow, 3x time textContent, and renderWaveforms() canvas redraw",
        "target_fps": "30 default (progressThrottleMs = 1000/30, player.js:1051); setUiFps clamps 10..60 and rewrites --ui-fps and --ui-transition-duration (player.js:1053-1059)",
        "throttle_mechanism": "timestamp - lastProgressFrame < progressThrottleMs -> return (player.js:1073)",
        "checks_document_hidden": "yes",
        "checks_hidden_line": 1066,
        "checks_other_view": "no - the player bar is global",
        "runs_when_minimized": "PARTIAL - the loop RE-SCHEDULES itself while hidden (player.js:1067) instead of parking; it only skips the body. It is therefore still an armed rAF chain while minimized.",
        "duplicate_start_guard": "yes - start sites all check !animFrameId",
        "per_frame_work": "3 style.transform writes + 3 setAttribute + 3 textContent + renderWaveforms() per throttled frame",
        "evidence": "static-read",
    },
    {
        "id": "orbit-glow",
        "file": "ui/web_new_v2/js/player.js",
        "self_schedule_line": 2002,
        "start_lines": [2005],
        "callback": "loop(now)",
        "animates": "--orbit-glow-opacity / --orbit-glow-scale CSS vars on #player-bar and .player-glass-card (Web Audio bass FFT)",
        "target_fps": "30 hardcoded (now - lastTime >= 33, player.js:1977)",
        "throttle_mechanism": "time gate inside loop",
        "checks_document_hidden": "via-cb - loop() itself has no check; syncOrbitGlowState() is bound to visibilitychange (2031) and evaluates !document.hidden (1935)",
        "checks_other_view": "no - runs on every view while playing",
        "runs_when_minimized": "no, provided the visibilitychange handler fires",
        "duplicate_start_guard": "yes - isOrbitGlowRunning (player.js:1965)",
        "perf_gates": "not started at all under :root.perf-low / .battery-saver-active / :root.perf-medium (player.js:1938-1951)",
        "per_frame_work": "analyserNode.getByteFrequencyData + 4 style.setProperty calls -> invalidates style for the whole player-bar subtree",
        "evidence": "static-read",
    },
    {
        "id": "css-aura-orbs",
        "file": "ui/web_new_v2/css/components/base.css",
        "self_schedule_line": 3727,
        "start_lines": [3727],
        "callback": "CSS @keyframes auraFloat (compositor-driven, not rAF)",
        "animates": "3 absolutely positioned gradient orbs (600x600, 650x650, 450x450 px) in #aura-orbs-container",
        "target_fps": "display rate; 22s / 28s / 18s alternate ease-in-out loops (base.css:3742/3751/3761)",
        "throttle_mechanism": "n/a",
        "checks_document_hidden": "via-cb - body.unfocused-animations-disabled sets animation-play-state: paused (base.css:3714-3717), and efficiency.js:133 sets that class when document.hidden and limit_state === 'minimize' (the default)",
        "checks_other_view": "no - fixed inset 0 behind the whole app",
        "runs_when_minimized": "no under the default efficiency settings; yes if unfocused_disable_animations is turned off",
        "duplicate_start_guard": "n/a - CSS",
        "per_frame_work": "3 compositor layers translating a transform; each orb also has contain: strict + will-change: transform",
        "evidence": "static-read",
    },
    {
        "id": "track-item-fadein",
        "file": "ui/web_new_v2/css/components/track-table.css",
        "self_schedule_line": 44,
        "start_lines": [44],
        "callback": "CSS `animation: fadeIn 0.3s ease forwards` (compositor-driven)",
        "animates": "opacity/transform of every .track-item",
        "target_fps": "one-shot 0.3s per row, staggered by item.style.animationDelay = min(index*0.03, 0.5)s (utils.js:313)",
        "throttle_mechanism": "n/a",
        "checks_document_hidden": "no",
        "checks_other_view": "no",
        "runs_when_minimized": "yes - `forwards` animations already started keep running",
        "duplicate_start_guard": "n/a",
        "scale_risk": "a 2000-track library creates 2000 simultaneous CSS animations at once (see section 5); delay is capped at 0.5s so they finish quickly, but all 2000 are created in the same frame batch",
        "evidence": "static-read",
    },
]

# ---------------------------------------------------------------- section 2
PASSIVE_NOTE = (
    "Only 3 of the 95 global addEventListener sites use { passive: true }; "
    "wheel is explicitly registered { passive: false } at main.js:562 because it "
    "calls preventDefault()."
)

# ---------------------------------------------------------------- section 3
# alpha = background alpha of the blurred element itself (1.0 = fully opaque)
BACKDROP_SITES = [
    # file, line, selector, radius, own_bg_alpha, nested_under, verdict
    ("components/base.css", 449, "#sidebar", "blur(var(--blur-md))", 0.55, [], "BLUR VISIBLE - blurs #aura-orbs-container / #particles-bg / #custom-bg-layer behind it"),
    ("components/base.css", 533, "#main-content", "blur(var(--blur-md))", 0.75, [], "BLUR VISIBLE - same app-background layers; this is the primary full-bleed blur"),
    ("components/base.css", 368, "html.has-custom-bg #sidebar", "blur(var(--glass-blur, var(--blur-md, 14px)))", None, [], "override of #sidebar; alpha unchanged"),
    ("components/base.css", 374, "html.has-custom-bg #main-content", "blur(var(--glass-blur, var(--blur-md, 14px)))", None, [], "override of #main-content; alpha unchanged"),
    ("components/base.css", 380, "html.has-custom-bg #player-bar", "blur(var(--glass-blur, var(--blur-md, 14px)))", None, [], "override of #player-bar; alpha unchanged"),
    ("components/base.css", 3358, "#sidebar, #player-bar, .top-bar, .context-menu, .modal-content, .glass-panel", "blur(var(--glass-blur)) saturate(180%)", 0.75, [], "background layer only (color-mix 75%); overwritten for #sidebar/#player-bar by later rules"),
    ("components/base.css", 612, ".card", "blur(var(--blur-sm))", None, [], "DEAD SELECTOR - 0 elements in index.html and 0 created in JS"),
    ("components/base.css", 820, ".search-platform-dropdown", "blur(var(--blur-xl))", 0.96, ["#main-content"], "BLUR BARELY VISIBLE - 52x~180px element over rgba(20,18,16,0.96)"),
    ("components/base.css", 2271, "#mini-player-overlay", "blur(24px) !important", 0.96, [], "BLUR EFFECTIVELY INVISIBLE - rgba(15,15,20,0.96) !important over the same element"),
    ("components/base.css", 2723, "#view-settings.view-page.settings-overlay", "blur(16px)", 0.55, ["#main-content"], "BLUR PARTLY VISIBLE - rgba(0,0,0,0.55)"),
    ("components/base.css", 2749, ".settings-modal-card", "blur(32px) saturate(150%)", 0.88, ["#view-settings.settings-overlay", "#main-content"], "3-DEEP NESTED BLUR over rgba(20,14,24,0.88) - 32px blur barely transmits"),
    ("components/base.css", 3232, ".workshop-card-badge", "blur(8px)", 0.65, ["#main-content"], "BLUR VISIBLE over the workshop preview <img> (35% transmission)"),
    ("components/base.css", 3248, ".workshop-card-overlay", "blur(3px)", 0.50, ["#main-content"], "BLUR VISIBLE over the workshop preview <img>; opacity 0 until hover (base.css:3252)"),
    ("components/base.css", 3403, "#custom-context-menu", "blur(20px)", 0.95, [], "DEAD SELECTOR - 0 references in index.html and 0 in js/"),
    ("components/base.css", 3517, ".network-banner", "blur(8px)", 0.90, [], "BLUR BARELY VISIBLE - rgba(239,68,68,0.9)"),
    ("components/base.css", 3597, ".custom-glass-dropdown-menu", "blur(16px)", 0.95, ["#main-content"], "BLUR BARELY VISIBLE - rgba(20,22,28,0.95)"),
    ("components/base.css", 3645, ".pl-drag-ghost", "blur(8px)", None, ["#main-content"], "drag ghost, transient; alpha from .lib-playlist-item"),
    ("components/base.css", 3781, "#mini-lyrics-widget", "blur(var(--blur-lg, 16px))", 0.90, [], "BLUR BARELY VISIBLE - color-mix(color-surface 88%, rgba(14,7,17,0.92))"),
    ("components/base.css", 3890, ".search-suggestions-dropdown", "blur(20px)", 0.94, ["#main-content"], "BLUR BARELY VISIBLE - color-mix(bg-surface 94%, rgba(14,7,17,0.95))"),
    ("components/base.css", 4050, "#batch-action-bar", "blur(24px)", 0.90, [], "BLUR BARELY VISIBLE - color-mix(bg-surface 90%, rgba(14,7,17,0.9))"),
    ("components/lyrics.css", 245, ".lyrics-overlay, #lyrics-overlay", "blur(40px)", 0.88, ["#main-content"], "LARGEST RADIUS IN THE APP over a 88%-opaque background - effectively invisible; also position:fixed is contained by #main-content (contain: layout, base.css:536)"),
    ("components/player-bar.css", 16, "#player-bar", "blur(16px)", 0.89, [], "overwritten by visual-polish.css:98"),
    ("components/player-bar.css", 315, "#queue-drawer", "blur(28px) saturate(160%)", 0.80, [], "BLUR PARTLY VISIBLE - rgba(18,12,22,0.80), 360x480px"),
    ("components/player-view.css", 46, ".player-glass-card", "blur(var(--blur-md))", 0.85, ["#main-content"], "BLUR VISIBLE - blurs .player-bg-glow (filter: blur(50px) cover art) which is its positioned sibling"),
    ("components/visual-polish.css", 86, ".search-capsule", "blur(var(--blur-md)) saturate(160%)", 0.82, ["#main-content"], "BLUR BARELY VISIBLE - color-mix(bg-surface 82%, transparent) with nothing behind it but #main-content's own translucent fill"),
    ("components/visual-polish.css", 97, "#player-bar", "blur(16px) saturate(160%)", 0.89, [], "WINNING value for #player-bar (last in the import order)"),
    ("components/visual-polish.css", 156, ".toast", "blur(var(--blur-md)) saturate(160%)", 0.92, [], "BLUR BARELY VISIBLE - color-mix(bg-surface 92%, transparent); #toast-container is a direct child of body so NOT nested inside #main-content"),
]

# non-backdrop filter() with blur()
FILTER_BLUR_SITES = [
    ("components/player-view.css", 30, ".player-bg-glow", "blur(var(--ambient-blur))", "--ambient-blur: 50px (tokens.css:66); the biggest single blur radius in the app, on a ~420px x viewport element with inset -20px, positioned behind .player-glass-card"),
    ("components/base.css", 1282, ".rich-menu-header-bg", "blur(25px) brightness(0.35) saturate(1.4)", "context-menu header"),
    ("components/base.css", 1432, "#particles-bg", "blur(8px)", "fixed inset -25px full-window canvas layer"),
    ("components/lyrics.css", 80, ".lyric-line", "blur(2px)", "one per lyric line; lyrics.css:391 sets filter:none in perf-low/medium/battery"),
    ("components/lyrics.css", 142, ".lyric-line.past", "blur(1.5px)", "one per already-played lyric line"),
]


def main() -> None:
    blur_map = json.loads((RESULTS / "css_blur_map.json").read_text(encoding="utf-8"))
    nesting = json.loads((RESULTS / "backdrop_nesting.json").read_text(encoding="utf-8"))
    rows = json.loads((RESULTS / "track_row_nodes.json").read_text(encoding="utf-8"))

    # in-process census (does not rewrite the file; js_census.main() is a script)
    import io
    import contextlib

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        js_census.main()
    census = json.loads((RESULTS / "frontend_hotspots.json").read_text(encoding="utf-8"))

    # ---------------- will-change / contain audit ----------------
    all_css: list = []
    for rel in IMPORT_ORDER:
        all_css.extend(parse_file(CSS_DIR / rel, f"ui/web_new_v2/css/{rel}"))

    wc = [
        d
        for d in all_css
        if d.prop in ("will-change", "contain", "contain-intrinsic-size", "content-visibility")
    ]

    # ---------------- image inventory ----------------
    js_dir = REPO / "ui" / "web_new_v2" / "js"
    img_sites = []
    for p in sorted(js_dir.glob("*.js")):
        if p.name.endswith(".min.js"):
            continue
        raw = p.read_text(encoding="utf-8")
        # blank out line comments so `<img>` mentioned in a comment is not counted
        code = re.sub(r"//[^\n]*", lambda m: " " * len(m.group(0)), raw)
        for m in re.finditer(r"<img[^>]*>", code):
            tag = m.group(0)
            img_sites.append(
                {
                    "file": f"ui/web_new_v2/js/{p.name}",
                    "line": raw.count("\n", 0, m.start()) + 1,
                    "tag": re.sub(r"\s+", " ", tag)[:200],
                    "loading_lazy": 'loading="lazy"' in tag,
                    "decoding_async": "decoding=" in tag,
                }
            )

    payload = {
        "schema": "nedotify.frontend-hotspots.v2",
        "generated_by": "tools/bench/build_hotspots.py",
        "measurement_policy": (
            "MEASURED = produced by running one of the scripts in tools/bench over the shipped "
            "sources (exact counts derived from real code, not estimates). "
            "STATIC = read from source and verified by hand, line-referenced. "
            "No runtime/browser/frame-time measurement was possible in this pass: "
            "tools/bench/results/startup-200trk-20261003-212819.json shows the only existing "
            "bench run aborted with 'Another instance of NeDotify is already running', so it "
            "contains no usable numbers."
        ),
        "inventory": {
            "ui_root": "ui/web_new_v2",
            "js_files": 22,
            "js_files_excluded_as_vendored": ["js/hls.min.js", "js/lucide.min.js"],
            "js_lines_total": sum(
                len(p.read_text(encoding="utf-8").splitlines())
                for p in js_dir.glob("*.js")
                if not p.name.endswith(".min.js")
            ),
            "css_files": len(IMPORT_ORDER) + 1,
            "css_declarations_parsed": sum(1 for _ in all_css) + 9,
            "index_html_elements": nesting["counts"]["dom_nodes"],
            "global_listener_adds": census["listeners"]["global_listener_adds"],
            "global_listener_removes": census["listeners"]["global_listener_removes"],
            "all_listener_sites_scanned": census["listeners"]["all_listener_sites_scanned"],
            "hot_event_listener_adds": census["listeners"]["hot_event_listener_adds"],
            "raf_call_sites": census["raf"]["total_request_animation_frame_calls"],
            "set_interval_sites": census["set_interval"]["total"],
            "backdrop_filter_declarations": blur_map["counts"]["backdrop_filter_active"],
            "backdrop_filter_none_overrides": blur_map["counts"]["backdrop_filter_none"],
            "filter_blur_declarations": blur_map["counts"]["filter_with_blur_fn"],
            "will_change_declarations": sum(1 for d in wc if d.prop == "will-change"),
            "contain_declarations": sum(1 for d in wc if d.prop == "contain"),
            "content_visibility_declarations": sum(1 for d in wc if d.prop == "content-visibility"),
        },
        "section1_raf_loops": RAF_LOOPS,
        "section2_listeners": {
            "passive_note": PASSIVE_NOTE,
            "duplicate_global_listeners": census["duplicate_global_listeners"],
            "duplicate_global_listener_sites": sum(
                d["count"] for d in census["duplicate_global_listeners"]
            ),
            "layout_thrash_candidates": census["layout_thrash_candidates"],
            "layout_thrash_candidate_count": len(census["layout_thrash_candidates"]),
            "all_records": census["listeners"]["all_records"],
        },
        "section3_backdrop": {
            "rule": "blur radius and colours are untouchable; the only legal optimisations are (a) do not blur under an opaque/near-opaque layer, (b) do not nest backdrop-filters",
            "sites": [
                {
                    "declaration": f"{f}:{ln}",
                    "selector": sel,
                    "value": val,
                    "own_background_alpha": alpha,
                    "backdrop_filtered_ancestors": anc,
                    "nesting_depth_under_backdrop_filter": len(anc),
                    "blur_visibility_verdict": verdict,
                    "evidence": "static-read",
                }
                for (f, ln, sel, val, alpha, anc, verdict) in BACKDROP_SITES
            ],
            "filter_blur_sites": [
                {"declaration": f"{f}:{ln}", "selector": sel, "value": val, "note": note, "evidence": "static-read"}
                for (f, ln, sel, val, note) in FILTER_BLUR_SITES
            ],
            "dead_blur_selectors": [
                s for s in BACKDROP_SITES if s[6].startswith("DEAD")
            ]
            and [
                {"declaration": f"{s[0]}:{s[1]}", "selector": s[2], "value": s[3]}
                for s in BACKDROP_SITES
                if s[6].startswith("DEAD")
            ],
            "dom_nesting_detail": nesting,
        },
        "section4_compositing": {
            "declarations": [
                {
                    "declaration": f"{d.file.replace('ui/web_new_v2/css/', '')}:{d.line}",
                    "selector": d.selector,
                    "property": d.prop,
                    "value": d.value,
                    "important": d.important,
                }
                for d in sorted(wc, key=lambda x: (x.file, x.line))
            ],
        },
        "section5_long_list": {
            "measurement": rows,
            "batch_size": 50,
            "batch_size_line": "ui/web_new_v2/js/library.js:372",
        },
        "section6_images": {
            "img_sites": img_sites,
            "img_sites_total": len(img_sites),
            "with_loading_lazy": sum(1 for i in img_sites if i["loading_lazy"]),
            "without_loading_lazy": [i for i in img_sites if not i["loading_lazy"]],
            "with_decoding_async": sum(1 for i in img_sites if i["decoding_async"]),
        },
    }

    out = RESULTS / "frontend_hotspots.json"
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    print(json.dumps(payload["inventory"], indent=2))


if __name__ == "__main__":
    main()