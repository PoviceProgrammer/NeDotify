# Frontend rendering hot spots — `ui/web_new_v2/`

**Phase:** MEASUREMENT / ANALYSIS only. No application file was modified. No commit.
**Date:** 2026-10-03
**Machine:** Windows, WebView2 (Chromium) via pywebview

---

## 0. How to read this document, and what "evidence" means here

Every claim below is labelled:

| Label | Meaning |
|---|---|
| **MEASURED** | Produced by running one of the scripts in `tools/bench/` over the *shipped* sources. The number comes from the real code (e.g. the real template literal, the real lucide `ICONS` map, the real CSS), not from an estimate. |
| **STATIC** | Read out of the source and verified by hand. Every row cites `file:line`. |

**There are no runtime numbers in this report.** This pass did not launch the app,
did not attach a CDP session and did not read any other subagent's benchmark output.
At the time this pass was written the only file in
`tools/bench/results/startup-*.json` was `startup-200trk-20261003-212819.json`,
and it aborted with `Another instance of NeDotify is already running; exiting
cleanly` (`child: {}`, no timings) — so it was unusable. Any `startup-2000trk-*.json`
or pyspy profile that a sibling pass has since written is **not** reflected in the
numbers below. Everything here is a *structural* hot-spot inventory: counts, nesting
depths, node counts, alpha values.

### Reproducing the artefacts

```
.venv_win\Scripts\python.exe tools\bench\css_inventory.py    # -> animation_declarations_inventory.json, css_blur_map.json
.venv_win\Scripts\python.exe tools\bench\dom_nesting.py      # -> backdrop_nesting.json
.venv_win\Scripts\python.exe tools\bench\js_census.py        # -> census (folded into frontend_hotspots.json)
node      tools\bench\track_row_nodes.js                     # -> track_row_nodes.json
.venv_win\Scripts\python.exe tools\bench\build_hotspots.py   # -> frontend_hotspots.json  (run last)
.venv_win\Scripts\python.exe tools\visual_guard\run_guard.py --write-css-baseline   # -> animation_declarations.json
.venv_win\Scripts\python.exe tools\bench\verify_frontend_report.py   # the gate for this document
```

`animation_declarations_inventory.json` and `css_blur_map.json` are byte-stable
across runs (they are emitted sorted by `(file, line, selector, property, value)`).
`verify_frontend_report.py` is the gate; see the note directly below for exactly what
it does and does not assert, because that distinction matters when a count in this
document is out of date.

**There are two `animation_declarations*.json` files and they are not
interchangeable.** `animation_declarations.json` is the *enforced* visual-guard
baseline (`nedotify.animation-declarations.v2`), keyed by `file.css|property` with
the values in a list under the key and **no line numbers anywhere** — line-numbered
keys were what made that guard's key-intersection structurally empty, so it passed
vacuously. `animation_declarations_inventory.json` is the *reporting* artefact
(`nedotify.animation-declarations.v1`), written by `css_inventory.py`, and it does
carry `file` and `line` per record. §7 describes both. Writing the line-numbered
report to the guard's path would restore exactly that vacuous behaviour, so the two
must never be merged again.

### What the gate asserts, and what it only reports

`verify_frontend_report.py` has three tiers, and conflating them is how a verifier
ends up crying wolf forever:

| Tier | Meaning | On failure |
|---|---|---|
| **structural** | A schema string, a key shape (`file.css\|property`, no line-number component), a count that must agree with the records stored beside it, a record whose `file:line` anchor must resolve to a real line of a real file, the presence of a string this document quotes. | non-zero exit |
| **document ↔ artefact** | A number this document quotes must equal the value read out of the artefact it cites. The verifier never writes a measurement down twice, so it cannot disagree with the tree — only with a stale document. | non-zero exit |
| **snapshot / drift** | A recorded measurement compared against the *current tree*, a line anchor whose line has since moved, or a hand-listed anchor whose position has drifted. These artefacts are hand-regenerated and the tree moves. | printed, **not** fatal, with the command that regenerates it |

Note what the structural tier does *not* claim: a line anchor that resolves to a
non-blank line is not proof that the right declaration is still there, so the
line-anchored artefacts are additionally checked for content presence (fatal) and
reported for position drift (not fatal). That split is deliberate — see §7.0 for why
line positions are not something to assert on.

The enforced half of the visual contract is `run_guard.py::css_declaration_guard`;
the gate deliberately does not duplicate it. When a *structural* check fails, the
fix is in the artefact or in this document. When a *snapshot* line differs, the fix
is to re-run the command the line prints and update the dated figures below.

### Baseline inventory (MEASURED)

The figures below are a **dated snapshot, not live values**. Each one names the
artefact it came from and, where the artefact is hand-regenerated, the command that
refreshes it. `verify_frontend_report.py` re-derives them from those artefacts and
prints any that have drifted from the tree as a non-fatal line, so a stale figure here
shows up as a dated note rather than as a wall of failures.

| Metric | Value | Artefact / how to refresh |
|---|---|---|
| First-party JS files (excl. vendored `hls.min.js`, `lucide.min.js`) | 21 | `frontend_hotspots.json` → `inventory` (derived from the tree by the gate) |
| Vendored JS bundles | 2 | same |
| First-party JS lines | 15 413 | `frontend_hotspots.json` → `inventory.js_lines_total`, recorded **2026-10-03** — the tree has since grown, see the gate's snapshot output |
| CSS files in the `@import` chain (+ `styles.css` entrypoint) | 11 | `animation_declarations_inventory.json` → `import_order` (10) + the entrypoint |
| Guard declarations (inventory) | **302** | `animation_declarations_inventory.json` → `counts.guard_declarations`; regenerate with `tools/bench/css_inventory.py` |
| CSS declarations parsed | **4 232** | same artefact → `counts.total_declarations_parsed`; regenerate the same way. **This is a live-ish figure: the CSS is still being edited, so re-run the scan before quoting it.** |
| Elements in `index.html` | 1 435 | `backdrop_nesting.json` → `counts.dom_nodes`; regenerate with `tools/bench/dom_nesting.py` |
| Global (`window`/`document`) `addEventListener` sites | **95** | `frontend_hotspots.json` → `inventory` |
| Global `removeEventListener` sites | 25 | same |
| All `add/removeEventListener` sites scanned (any target) | 348 | same |
| Listener sites on hot event types | 224 | same |
| `requestAnimationFrame` call sites | 24 | same |
| `setInterval` sites | 2 | same |
| Active `backdrop-filter` declarations | **50** | `css_blur_map.json` → `counts.backdrop_filter_active` |
| `backdrop-filter: none` overrides | 12 | `css_blur_map.json` → `counts.backdrop_filter_none` |
| `filter: …blur()` declarations | 9 | `css_blur_map.json` → `counts.filter_with_blur_fn` |
| `will-change` declarations | 15 | `animation_declarations_inventory.json` → `counts.by_property` |
| `contain` declarations | 7 | same |
| `content-visibility` declarations | **2** | same — one on `.track-item`, one on the queue drawer's own row (§4.1) |
| `contain-intrinsic-size` declarations | **2** | same — one per `content-visibility`, because the two rows have different heights (§4.1) |

---

## 1. rAF loops and animation drivers

**MEASURED:** 24 `requestAnimationFrame` call sites, 2 `setInterval` sites
(`tools/bench/results/frontend_hotspots.json` → `inventory`, `section1_raf_loops`).

Six of the 24 rAF sites are *one-shot* / self-terminating and are not loops:
`hotkeys.js:224` (focus after navigation), `library.js:714` and `library.js:746`
(playlist-item stagger), `player.js:2039` (`requestThrottledWaveformRender`,
flag-guarded), `search.js:469` (rAF-chained batch renderer, `SEARCH_BATCH_SIZE = 30`
at `search.js:440`).

### 1.1 The five real loops

| # | Loop | file:line (self-schedule) | What it animates | Target FPS | `document.hidden` check? | Minimized? | Other view active? |
|---|---|---|---|---|---|---|---|
| L1 | `animate(timestamp)` — particles | `js/particles.js:405` (starts `38, 280, 465, 479`) | `<canvas>` particle field in `#particles-bg` | **24** (`particles.js:17`; `setParticlesFps` 5–30; efficiency/battery force 15 at `:484`, `:493`) | **YES** — `:400` | **No** — stops, `animFrameId = null` | **No** — `#particles-bg` is `position: fixed; inset: -25px; z-index: 1` (`base.css:1425`), it covers every view |
| L2 | `draw(timestamp)` — visualizer | `js/visualizer.js:280` (starts `43, 78, 86, 98, 174`) | `#visualizer-canvas`, `#home-visualizer-canvas` (48 bars) | **24** (`visualizer.js:16`; `setVisualizerFps` 5–60; efficiency forces 15 at `:448`) | **YES** — `documentVisible`, `:255` | **No** | **YES** — stops when no canvas is visible (`offsetParent !== null` && `closest('.view-page').classList.contains('active')`), `:263–275` |
| L3 | `animateProgress(timestamp)` | `js/player.js:1070` (starts `1031, 1067, 1215, 1476`) | pb/pp/mp progress-fill `transform`, 3× `aria-valuenow`, 3× time text, `renderWaveforms()` canvas | **30** (`progressThrottleMs`, `player.js:1051`; `setUiFps` 10–60 and rewrites `--ui-fps` *and* `--ui-transition-duration`, `:1053–1059`) | **PARTIAL** — `:1066` | **No** — the loop *re-schedules itself while hidden* (`:1067`) instead of parking; it is still an armed rAF chain | **No** — the player bar is global |
| L4 | `loop(now)` — orbit glow | `js/player.js:2002` (starts `:2005`) | `--orbit-glow-opacity` / `--orbit-glow-scale` on `#player-bar` and `.player-glass-card`, driven by a Web Audio bass FFT | **30** hardcoded (`now - lastTime >= 33`, `:1977`) | **via callback** — `loop()` has no check; `syncOrbitGlowState` is bound to `visibilitychange` (`:2031`) and tests `!document.hidden` (`:1935`) | **No**, provided the handler fires | **No** |
| L5 | CSS `@keyframes auraFloat` | `css/components/base.css:3727` | 3 gradient orbs, 600×600 / 650×650 / 450×450 px | display rate, 22 s / 28 s / 18 s `alternate ease-in-out` (`:3742`, `:3751`, `:3761`) | **via callback** — `body.unfocused-animations-disabled` sets `animation-play-state: paused` (`:3714–3717`), and `efficiency.js:133` sets that class when `document.hidden` and `limit_state === 'minimize'` (the default) | **No** under default efficiency settings | **No** — fixed `inset: 0` behind the whole app |

Additional **STATIC** finding on L5/L2 — *idle loops are intentional but permanent*:
`visualizer.js:277–280` re-requests rAF even when paused (comment: "Ambient idle
loop … instead of freezing after a single near-invisible frame"). So on the Home
or Player view the app holds a 24 fps canvas loop forever, paused or playing.

### 1.2 Pause-when-hidden audit — what actually works

* **Works:** L1 (`particles.js:400`), L2 (`visualizer.js:255`), L4 (`player.js:1935` via `visibilitychange`), L5 (`base.css:3714` via `efficiency.js`).
* **Leaky:** L3. `player.js:1066–1069`:
  ```js
  if (document.hidden) {
      animFrameId = requestAnimationFrame(animateProgress);
      return;
  }
  ```
  It re-arms itself in the hidden branch. Correct shape would be `animFrameId = null; return;` (which is exactly what L1 and L2 do). This is the one loop that is **not** pausable as written.

### 1.3 `setInterval` drivers

| Site | Interval | Hidden-aware? | Verdict |
|---|---|---|---|
| `js/main.js:708` `setInterval(updateGreeting, 5*60*1000)` | 5 min | no | Negligible; also never cleared but the interval is intentional and app-lifetime |
| `js/lyrics.js:250` `setInterval(() => adjustLyricsOffset(stepMs), 90)` | 90 ms | no | User-gated hold-to-repeat; `stop()` is bound to `pointerup / pointerleave / pointercancel / keyup / blur` (`lyrics.js:241–257`) so it cannot outlive the press |

### 1.4 Duplicate-loop risk

* **L1 `particles`**: guarded — `initParticles()` cancels `animFrameId` first (`particles.js:208–211`), and `animateFn` is module-level. **No duplicate rAF loop.**
* **L2 `visualizer`**: guarded — every start site tests `!animFrameId`. **No duplicate.**
* **L3 `player-progress`**: guarded — `if (!animFrameId)` at `player.js:1474`, `:1213`, `:1030`. **No duplicate.**
* **L4 `orbit-glow`**: guarded — `isOrbitGlowRunning` (`player.js:1965`). **No duplicate.**
* **L5 `aura-orb`**: pure CSS. **No duplicate.**

**However there IS a real duplicate-registration bug next to L1** — see §2.4:
`initParticles()` leaks four `window` listeners *every time it is called*, and it is
called from the `input` handler of three sliders.

### 1.5 Continuous CSS animations (MEASURED: 14 `infinite` animations)

| Declaration | Selector | Infinite? | Live? |
|---|---|---|---|
| `base.css:166` | `.app-splash-shimmer` | yes | splash only, removed on ready (`main.js:542`) |
| `base.css:1444` | `.particle` | yes | **DEAD — 0 elements** in `index.html` and 0 created in JS |
| `base.css:1463/1464` | `.animate-spin-slow`, `.animate-spin` | yes | live |
| `base.css:1486`, `:1537` | `.spinner` | yes | 3 spinners in `index.html` + dynamically created |
| `base.css:1995` | `.shimmer-bg` | yes | live (artist profile) |
| `base.css:3380` | `.skeleton`, `.skeleton*`, `.ui-shimmer` | yes | live; disabled on inactive views (`base.css:3038–3042`) |
| `base.css:3727` | `.aura-orb` | yes | live (3 orbs) |
| `player-bar.css:94` | `.pb-cover.spinning` | yes | live |
| `track-table.css:137` | `.track-equalizer-bars .eq-bar` | yes | **DEAD — 0 elements**, 0 refs in JS |
| `track-table.css:63` | `.track-item` | **no** (`fadeIn 0.3s forwards`) | live — but **2000 instances at once** for a 2000-track library (§5) |

---

## 2. Event listeners

**MEASURED** census in `tools/bench/results/frontend_hotspots.json` →
`section2_listeners` (`all_records` holds all 348 sites with `passive`, `capture`,
detected `reads` / `writes`, and `enclosing_function`).

Scanner notes: the handler body is resolved 2 levels through same-file local
function declarations, so a handler that delegates to a helper is classified by
the helper's body too. Handlers reached only through a *callback parameter* are
not resolvable by a static scan and are listed in §2.5 as MANUAL.

### 2.1 Global `window`/`document` listeners of interest

| file:line | Target | Event | `{passive:true}`? | Throttle / debounce / rAF-coalesce? | Notes |
|---|---|---|---|---|---|
| `js/main.js:562` | `document` | `wheel` | **NO — `{ passive: false }`** | none | Reads `scrollWidth/clientWidth/scrollHeight/clientHeight` then `preventDefault()` + `scrollLeft` write. A non-passive **document-level** wheel listener forces the compositor to wait on the main thread for *every* wheel event app-wide. Reads only → no thrash. |
| `js/lyrics.js:564` | `.lyrics-viewport` | `wheel` | **NO — `{ passive: false }`** | none | Needs `preventDefault()`. Reads `viewport.clientHeight` (`ensureMeasured` → `measureViewport`) and `track.offsetHeight`, then writes `style.paddingTop/paddingBottom` and `style.transform` in the same handler. Element-scoped and only 2 instances. |
| `js/lyrics.js:590` | `.lyrics-viewport` | `pointermove` | not set | none | Same read+write shape as the wheel handler; drag-gated by `st.dragging`. |
| `js/lyrics.js:1113` | `window` | `mousemove` | not set | none | **Layout thrash** (see §2.3). |
| `js/particles.js:303` | `window` | `mousemove` | **YES `{ passive: true }`** | `setTimeout(…, 32)` leading-edge throttle (`particles.js:287–297`) | Correct. But re-registered on every `initParticles()` call (§2.4). |
| `js/particles.js:270` | `window` | `resize` | n/a | `setTimeout(performResize, 100)` debounce (`:263–267`) | Re-registered on every `initParticles()` call (§2.4). |
| `js/visualizer.js:117` | `window` | `resize` | n/a | **NONE** | `resizeCanvas()` sets `canvas.width/height` from `parentElement.offsetWidth/offsetHeight` on **every** resize event. Unthrottled, so a drag-resize fires it at input rate. |
| `js/player.js:1763` | `window` | `resize` | n/a | **NONE** | `document.querySelectorAll('.waveform-canvas')` on every resize event — a full-document query per resize tick. Module-level, never removed. |
| `js/player.js:2069` | `window` | `resize` | n/a | **NONE** | Inside `setupMagneticWaveformListeners`, per progress track: sets `cachedRect = null`. Registered at `DOMContentLoaded` (`:2074–2078`). |
| `js/utils.js:692` | `window` | `resize` | n/a | none | Floating-menu guard, **armed only while a menu is open** (`:689`) and torn down in `_dismiss` (`:682–686`). Good pattern. |
| `js/utils.js:693` | `window` | `scroll` | n/a (`capture: true`) | none | **`capture: true` on window fires for every scroll event of every scrollable in the document**, while a context menu is open. |
| `js/lyrics.js:218` | `document` | `keydown` | n/a | early-return | Escape closes the lyrics overlay. |
| `js/pages.js:32` | `document` | `keydown` | n/a | early-return | Escape closes settings. |
| `js/queue.js:55` | `document` | `keydown` | n/a | early-return | Escape closes the queue. |
| `js/hotkeys.js:121` | `window` | `keydown` | n/a | none | Single authoritative global hotkey handler; early-returns for editable targets (`:140–145`). |
| `js/utils.js:973`, `js/utils.js:1256` | `document` | `keydown` | n/a | none | See §2.4 (context-menu pair churn / batch-bar). |
| `js/library.js:414` | scroll parent | `scroll` | **YES `{ passive: true }`** | none | Infinite-scroll loader; 3 layout reads per event (`:409–410`), properly removed via the returned cleanup (`:415`) which `renderLibraryList` calls first (`:419`). |
| `js/artist_profile.js:699` | `listContainer` | `scroll` | not set | none | 3 layout reads + `loadMore()` when within 20 px; **re-registered on every artist-profile render** on a freshly created container. |
| `js/equalizer.js:125, 228`, `js/settings.js:653` | sliders | `input` | n/a | none | `settings.js:643–646` fires `onChange` on **every** `input` event — the reason `initParticles()` is called dozens of times per slider drag. |
| `js/main.js:730`, `js/search.js:58`, `js/onboarding.js:143` | inputs | `input` | n/a | search.js debounces (`:69`) | — |

### 2.2 Layout-thrash candidates — handlers that read AND write layout in one handler

**MEASURED: 34 sites** (`section2_listeners.layout_thrash_candidates`, sorted
global-first). Global ones (10):

| file:line | Target | Event | Reads | Writes |
|---|---|---|---|---|
| `js/lyrics.js:1113` | `window` | `mousemove` | `offsetWidth`, `offsetHeight`, `innerWidth`, `innerHeight` | `style.left`, `style.top` |
| `js/library.js:818` | `document` | `pointermove` | `getBoundingClientRect` (via `moveDrag`) | `style.*`, `insertBefore` |
| `js/library.js:819` | `document` | `pointerup` | `getBoundingClientRect` | `style.*`, `remove()` |
| `js/lyrics.js:278` | `document` | `nedotify:position_changed` | `clientHeight`, `offsetTop` (via `updateLyricsPosition`) | `classList` |
| `js/lyrics.js:283` | `document` | `nedotify:lyrics_ready` | `clientHeight`, `offsetTop` | `innerHTML`, `appendChild`, `style.*`, `textContent` |
| `js/queue.js:60` | `document` | `nedotify:queue_updated` | `getBoundingClientRect` | `innerHTML`, `appendChild`, `style.*` |
| `js/queue.js:70` | `document` | `nedotify:track_changed` | `getBoundingClientRect` | `innerHTML`, `appendChild`, `style.*` |
| `js/library.js:81` | `document` | `nedotify:batch_download_finished` | `offsetHeight` | `innerHTML`, `appendChild`, `style.*`, `textContent` |
| `js/utils.js:172` | `document` | `error` | `offsetHeight`, `innerWidth`, `innerHeight` | `innerHTML`, `style.*`, `textContent`, `appendChild` |
| `js/player.js:2075` | `document` | `DOMContentLoaded` | `getBoundingClientRect` | `classList` |

24 element-scoped sites are listed in the JSON; the hot ones are
`js/lyrics.js:564 / 579 / 1060`, `js/library.js:99 / 214 / 414 / 660 / 777 / 822 / 946 / 974`,
`js/player.js:919 / 2055`, `js/queue.js:99 / 182 / 227 / 246`,
`js/settings.js:1572 / 3008`, `js/utils.js:492 / 500`,
`js/artist_profile.js:699`.

### 2.3 Notable thrash detail

**`js/lyrics.js:1077–1096` (inside `initMiniLyricsWidget`)** — the worst
read-after-write loop in the app, and it is a *protected* file (in-flight work):

```js
const onMouseMove = (moveEvt) => {
  …
  const maxX = window.innerWidth  - widget.offsetWidth  - 12;   // READ (layout)
  const maxY = window.innerHeight - widget.offsetHeight - (84+16); // READ (layout)
  widget.style.left = `${nextX}px`;   // WRITE
  widget.style.top  = `${nextY}px`;   // WRITE
};
window.addEventListener('mousemove', onMouseMove);   // :1113 — no passive, no throttle
```
`offsetWidth`/`offsetHeight` are re-read *after* the previous event's style
writes, forcing a synchronous layout on every `mousemove`. The rect is available
from the `mousedown` handler (`:1065`, `widget.getBoundingClientRect()`), so the
dimensions could be cached once per drag.

**Contrast — a correctly written one.** `js/player.js:2051–2061`
(`setupMagneticWaveformListeners`) caches the rect on `mouseenter` and rAF-coalesces
the redraw via `requestThrottledWaveformRender` (`player.js:2036–2043`). That is the
shape the other pointer handlers should follow.

### 2.4 Duplicate global listeners (the leak census)

**MEASURED: 17 `(target, event)` pairs are registered more than once, totalling
52 registration sites**, versus 25 `removeEventListener` sites.

| Count | Target + event | Sites |
|---|---|---|
| **6** | `document` `visibilitychange` | `efficiency.js:158`, `particles.js:30`, `player.js:1212`, `player.js:2031`, `settings.js:2236`, `visualizer.js:74` |
| **5** | `document` `click` | `equalizer.js:96`, `player.js:992`, `search.js:100`, `search.js:1079`, `utils.js:972` |
| **5** | `document` `keydown` | `lyrics.js:218`, `pages.js:32`, `queue.js:55`, `utils.js:973`, `utils.js:1256` |
| **5** | `window` `resize` | `particles.js:270`, `player.js:1763`, `player.js:2069`, `utils.js:692`, `visualizer.js:117` |
| 3 | `document` `DOMContentLoaded` | `boot.js:22`, `home.js:1108`, `player.js:2075` |
| 3 | `document` `nedotify:track_changed` | `lyrics.js:271`, `queue.js:70`, `utils.js:588` |
| 3 | `window` `blur` | `efficiency.js:153`, `player.js:2029`, `settings.js:2234` |
| 3 | `window` `focus` | `efficiency.js:154`, `player.js:2030`, `settings.js:2235` |
| 3 | `window` `nedotify:page_changed` | `events.js:13`, `utils.js:694`, `visualizer.js:95` |
| 2 each | `document` `nedotify:state_changed`, `document` `nedotify:track_downloaded`, `window` `app:artists_avatars_ready`, **`window` `mousemove`**, `window` `nedotify:app_ready`, `window` `nedotify:efficiency_state`, `window` `nedotify:toast`, `window` `pywebviewready` | see JSON |

Most of the `2×`/`3×` groups are **benign by design** (independent features each
subscribing to `visibilitychange`; `main.js:364–365` guards `init()` so
`initLyrics`/`initLibrary`/etc. run once). The ones that matter:

#### 2.4.1 `initParticles()` leaks four `window` listeners per call — **real, unbounded**

`js/particles.js:263–305` creates fresh closures and then calls
`removeEventListener` **with the new closure**, which cannot match anything that
was previously added:

```js
let resizeTimeout = null;
const onResize = () => { … };                          // NEW closure every call
window.removeEventListener('resize', onResize);       // removes nothing
window.addEventListener('resize', onResize);          // +1
```

`initParticles()` is called from **8 sites**:
`js/settings.js:124` (`slider-particles-count` `input`), `:129` (`…-size`), `:134`
(`…-speed`), `:202` (shape button), `:614` (particles toggle), `:689`, `:1315`
(`applyResourceToggle`), plus `js/main.js:470` at boot.

`settings.js:643–646` fires `onChange` on **every unthrottled `input` event**, so
dragging `slider-particles-count` from 30 → 80 emits roughly 50 `input` events →
≈ 50 `initParticles()` calls → **≈ 50 permanent `window resize` + 50
`window mousemove` + 50 `window mouseleave` + 50 `window
nedotify:mini_player_toggled` listeners** for the rest of the session. The rAF loop
itself *is* correctly guarded, so this is purely a listener leak plus a
full particle-array rebuild per input event.

#### 2.4.2 `showTrackContextMenu()` — non-idempotent document listener pair

`js/utils.js:971–974` registers `document click` + `document keydown` inside a
`setTimeout(…, 50)`, and `closeMenu()` (`:950–957`) removes them. But `:707–710`
clears `activeRichMenu` *without* removing the previous invocation's listeners, and
each invocation declares its own `onDocumentClick`/`onKeyDown`. Two opens inside
50 ms ⇒ two live pairs, of which the older one becomes an inert permanent
`document click` listener. Bounded at ~2 pairs but it never converges.

#### 2.4.3 `initMiniLyricsWidget()` — unguarded global listener

`js/lyrics.js:1129` `window.addEventListener('lyrics:line-changed', …)` has no
`_bound` guard (compare `visualizer.js:141` which does). Currently harmless because
`init()` runs once, but it is the exact shape that breaks if `initLyrics()` is ever
re-entered.

### 2.5 Not statically resolvable (MANUAL, verified by reading)

* `js/player.js:1668` — `document.addEventListener('mousemove', onMouseMove)` inside
  `setupDragBar`. `onMouseMove` calls `getPct(e2)` (`:1655–1658`), which does
  `track.getBoundingClientRect()` on **every** event, and `onDrag` then writes the
  progress-fill `transform`. **Read-after-write per mousemove during any scrub.**
  Listeners are removed correctly on `mouseup` (`:1663–1666`).
* `js/player.js:2055` — `el.addEventListener('mousemove', …)` on the waveform
  tracks: `getBoundingClientRect()` is *cached* from `mouseenter`, and the redraw is
  rAF-coalesced. **Not** a thrash source; listed so the guard knows it is already fine.

---

## 3. GLASS / `backdrop-filter` MAP — nesting depth and what is actually painted behind each

> **This is the gating section.** The rule is: blur radius and colours are
> untouchable. The only legal optimisations are (a) **do not blur under an opaque or
> near-opaque layer**, and (b) **do not nest `backdrop-filter`**.

**MEASURED:** 50 active `backdrop-filter` declarations + 12 `none` overrides +
9 `filter: … blur()` declarations across 10 CSS files, all reproduced in
`tools/bench/results/css_blur_map.json`. The `backdrop-filter` count was
cross-checked against a plain regex (`Select-String '^\s*(-webkit-)?backdrop-filter\s*:'`)
and matches exactly: **62 declarations** = 34 unprefixed + 28 `-webkit-`.

**Nesting** was resolved by parsing `index.html` into a DOM tree
(`tools/bench/dom_nesting.py`, 1 435 elements) and walking each matched element's
ancestor chain against every CSS rule to find ancestors that create a containing
block (`filter`, `backdrop-filter`, `transform`, `perspective`, `opacity`,
`contain`, `will-change`, `mask`, `clip-path`, `mix-blend-mode`, `isolation`).
Full per-element chains are in `tools/bench/results/backdrop_nesting.json`.

### 3.1 The structural fact that dominates everything

```
body
├─ #custom-bg-layer         (user background image, filter: blur(Npx))
├─ #custom-bg-dim-layer
├─ #aura-orbs-container     contain: strict  — 3 infinite CSS-animated orbs
├─ #particles-bg            filter: blur(8px) — rAF canvas
├─ #title-bar
├─ #toast-container         → .toast
├─ #network-banner
├─ #mini-player-overlay
└─ #app-container
   ├─ #sidebar              ← backdrop-filter, depth 0
   ├─ #main-content         ← backdrop-filter, depth 0   ***THE BLUR ROOT***
   │   ├─ #view-home
   │   ├─ #view-search      → .search-capsule, .search-platform-dropdown, .search-suggestions-dropdown
   │   ├─ #view-library     → .lib-playlist-item.pl-drag-ghost
   │   ├─ #view-player      → .player-bg-glow, .player-glass-card ×2
   │   ├─ #lyrics-overlay   ← backdrop-filter, nested in #main-content
   │   ├─ #view-profile
   │   └─ #view-settings    ← backdrop-filter, nested in #main-content
   │       └─ .settings-modal-card ← backdrop-filter, 3-deep
   ├─ #player-bar           ← backdrop-filter, depth 0
   ├─ #queue-drawer         ← backdrop-filter, depth 0
   ├─ #mini-lyrics-widget   ← backdrop-filter, depth 0
   ├─ #batch-action-bar     ← backdrop-filter, depth 0
   ├─ #playlist-context-menu / #track-options-menu  (background only, base.css:3358)
   └─ 4 modals + #onboarding-wizard
```

`#aura-orbs-container` and `#particles-bg` sit at `z-index: 0/1` *below*
`#app-container` in paint order. **They are the content the three depth-0 glass
panels are blurring** — which is why those three blurs are visually load-bearing
and must not be removed. Everything *inside* `#main-content` is re-blurring an
already-blurred, ~75 %-opaque surface.

### 3.2 Nesting-depth table

`BF-ancestor` = number of ancestors that themselves carry an active
`backdrop-filter`. `Own α` = alpha of the element's own background.

| # | Declaration | Selector | Radius | BF-ancestor | Nest depth | Own α | What is painted directly behind it | Blur visible? |
|---|---|---|---|---|---|---|---|---|
| 1 | `base.css:449` | `#sidebar` | `blur(var(--blur-md))` → `--glass-blur` = 8 px | 0 | **0** | 0.55 | orbs, particles, custom bg, body | **YES — load-bearing** |
| 2 | `base.css:533` | `#main-content` | `blur(var(--blur-md))` → 8 px | 0 | **0** | 0.75 | orbs, particles, custom bg, body | **YES — load-bearing** |
| 3 | `player-view.css:46` | `.player-glass-card` (×2) | `blur(var(--blur-md))` → 8 px | 1 (`#main-content`) | **1** | 0.85 | `.player-bg-glow` (`filter: blur(50px)` cover art) — a real, moving image | **YES** |
| 4 | `lyrics.css:245` | `.lyrics-overlay, #lyrics-overlay` | **`blur(40px)`** | 1 (`#main-content`) | **1** | **0.88** | `#main-content`'s own 75 %-α blurred fill | **NO — 12 % transmission. Largest radius in the app, effectively invisible.** |
| 5 | `base.css:2749` | `.settings-modal-card` | **`blur(32px) saturate(150%)`** | 2 (`#view-settings` → `#main-content`) | **2** | **0.88** | `#view-settings`' `rgba(0,0,0,0.55)` over `#main-content` | **NO — 3-deep chain, 12 % transmission** |
| 6 | `base.css:2723` | `#view-settings.view-page.settings-overlay` | `blur(16px)` | 1 (`#main-content`) | **1** | 0.55 | view content behind the overlay | partly (45 % transmission) |
| 7 | `base.css:2271` | `#mini-player-overlay` | **`blur(24px)`** | 0 | **0** | **0.96** `!important` | body background | **NO — 4 % transmission** |
| 8 | `base.css:3781` | `#mini-lyrics-widget` | `blur(var(--blur-lg, 16px))` → 12 px | 0 | **0** | 0.90 | page content | barely (10 %) |
| 9 | `base.css:4050` | `#batch-action-bar` | **`blur(24px)`** | 0 | **0** | 0.90 | page content | barely (10 %) |
| 10 | `player-bar.css:315` | `#queue-drawer` | **`blur(28px) saturate(160%)`** | 0 | **0** | 0.80 | page content | partly (20 %) — 360×480 px |
| 11 | `visual-polish.css:98` | `#player-bar` | **`blur(16px) saturate(160%)`** (winning value) | 0 | **0** | 0.89 | page content / body | barely (11 %) |
| 12 | `player-bar.css:16` | `#player-bar` | `blur(16px)` — **overwritten by #11** | 0 | 0 | — | — | — |
| 13 | `base.css:3358` | `#sidebar, #player-bar, .top-bar, .context-menu, .modal-content, .glass-panel` | `blur(var(--glass-blur)) saturate(180%)` | 0 | 0 | 0.75 | background-only layer; `#sidebar`/`#player-bar` overridden later | background layer |
| 14 | `visual-polish.css:86` | `.search-capsule` | `blur(var(--blur-md)) saturate(160%)` → 8 px | 1 (`#main-content`) | **1** | 0.82 | nothing — `#main-content`'s flat translucent fill | **barely** |
| 15 | `base.css:702` | `.search-capsule` | `blur(var(--blur-sm))` → 6 px — **overwritten by #14** | 1 | 1 | — | — | — |
| 16 | `base.css:820` | `.search-platform-dropdown` | `blur(var(--blur-xl))` → 16 px | 1 (`#main-content`) | **1** | **0.96** | `#main-content` fill | **NO — 52×~180 px over 96 %-opaque** |
| 17 | `base.css:3890` | `.search-suggestions-dropdown` | **`blur(20px)`** | 1 (`#main-content`) | **1** | **0.94** | `#main-content` fill | **NO** |
| 18 | `base.css:3597` | `.custom-glass-dropdown-menu` | `blur(16px)` | 1 (`#main-content`) | **1** | **0.95** | `#main-content` fill | **NO** |
| 19 | `base.css:3645` | `.pl-drag-ghost` | `blur(8px)` | 1 (`#main-content`) | **1** | (`.lib-playlist-item`) | list background | partly; transient drag ghost |
| 20 | `visual-polish.css:156` | `.toast` | `blur(var(--blur-md)) saturate(160%)` | 0 (`#toast-container` is a **body** child) | **0** | 0.92 | body / app background | barely (8 %) |
| 21 | `base.css:3517` | `.network-banner` | `blur(8px)` | 0 | **0** | **0.90** | body | barely (10 %) |
| 22 | `base.css:3232` | `.workshop-card-badge` | `blur(8px)` | 1 (`#main-content`) | **1** | 0.65 | the workshop preview `<img>` | **YES** (35 % transmission over an image) |
| 23 | `base.css:3248` | `.workshop-card-overlay` | `blur(3px)` | 1 (`#main-content`) | **1** | 0.50 | the workshop preview `<img>` | **YES**, but `opacity: 0` until `:hover` (`:3252`) |
| 24 | `base.css:368/374/380` | `html.has-custom-bg #sidebar / #main-content / #player-bar` | `blur(var(--glass-blur, var(--blur-md, 14px)))` | 0 | 0 | same | same | overrides of #1/#2/#11 when a custom background is set |
| 25 | `base.css:612` | `.card` | `blur(var(--blur-sm))` → 6 px | — | — | — | — | **DEAD — 0 elements** |
| 26 | `base.css:3403` | `#custom-context-menu` | **`blur(20px)`** | — | — | 0.95 | — | **DEAD — 0 refs in HTML and JS** |

### 3.3 Where the two legal optimisations are available

**Rule (a) — do not blur under an opaque / near-opaque layer. 11 sites qualify**
(rank-ordered by radius, since blur cost scales with radius × area):

| Declaration | Radius | Own α | Transmission |
|---|---|---|---|
| `lyrics.css:245` `#lyrics-overlay` | 40 px | 0.88 | 12 % |
| `base.css:2749` `.settings-modal-card` | 32 px | 0.88 | 12 % |
| `player-bar.css:315` `#queue-drawer` | 28 px | 0.80 | 20 % |
| `base.css:2271` `#mini-player-overlay` | 24 px | 0.96 | **4 %** |
| `base.css:4050` `#batch-action-bar` | 24 px | 0.90 | 10 % |
| `base.css:3890` `.search-suggestions-dropdown` | 20 px | 0.94 | 6 % |
| `base.css:3403` `#custom-context-menu` | 20 px | 0.95 | **dead anyway** |
| `visual-polish.css:97` `#player-bar` | 16 px | 0.89 | 11 % |
| `base.css:3597` `.custom-glass-dropdown-menu` | 16 px | 0.95 | 5 % |
| `base.css:820` `.search-platform-dropdown` | 16 px | 0.96 | **4 %**, and only 52 px wide |
| `visual-polish.css:156` `.toast` | 8 px | 0.92 | 8 % |

`#mini-player-overlay` (`4 %` transmission over a 96 %-opaque `!important`
background) and `#search-platform-dropdown` / `#custom-context-menu` (4–5 % over
full-viewport-size-ish `!important` fills) are the two strongest cases.

**Rule (b) — do not nest. 13 of the 50 active sites are nested** under
`#main-content` (rows 3–6, 14–19, 22–23). The worst chain is
`.settings-modal-card` → `#view-settings.settings-overlay` → `#main-content`:
**three stacked backdrop-filters, radii 32 px / 16 px / 8 px, where the innermost
(the most expensive, largest-radius one) is the least visible.**

Two dead selectors (`base.css:612 .card`, `base.css:3403 #custom-context-menu`)
cost nothing at runtime but also mean `efficiency.js:6`'s IntersectionObserver
(`'.card, .glass-panel, .player-glass-card, .settings-modal-card'`) has one fewer
selector than it appears to.

### 3.4 `filter: … blur()` (not backdrop — but also expensive)

| Declaration | Selector | Value | Note |
|---|---|---|---|
| `player-view.css:30` | `.player-bg-glow` | **`blur(var(--ambient-blur))` = `blur(50px)`** | Largest radius in the app. ~420 px × viewport, `inset: -20px`, `z-index: 0`, painted behind both `.player-glass-card`s. `filter` on a large element forces an offscreen surface at full size. `.player-bg-glow-downscaled` (`player-view.css:36–40`) adds `contain: strict` + `scale(1.1)` — so the surface is 10 % larger than needed. |
| `base.css:1432` | `#particles-bg` | `blur(8px)` | full-window canvas layer, `inset: -25px` |
| `base.css:1282` | `.rich-menu-header-bg` | `blur(25px) brightness(0.35) saturate(1.4)` | context-menu header |
| `lyrics.css:80` | `.lyric-line` | `blur(2px)` | **one per lyric line**; `lyrics.css:392` neutralises it in perf-low/medium/battery |
| `lyrics.css:143` | `.lyric-line.past` | `blur(1.5px)` | one per already-played line |

---

## 4. `will-change` / `contain` / `content-visibility` audit

**MEASURED: 15 `will-change`, 7 `contain`, 2 `content-visibility`,
2 `contain-intrinsic-size`.** Machine-readable copy in
`tools/bench/results/frontend_hotspots.json` → `section4_compositing.declarations`
and in `tools/bench/results/animation_declarations_inventory.json` →
`counts.by_property` (regenerate with `tools/bench/css_inventory.py`).

The count is **2, not 1**, because there are two distinct row geometries in the app,
not one:

* `.track-item` in `css/components/track-table.css` — the unified track table row.
* `#queue-drawer-content .track-item` in `css/components/player-bar.css` — the queue
  drawer reuses the same class with different padding and a smaller cover, so its row
  is **56 px**, not the table's 66 px.

A single shared `contain-intrinsic-size` would be wrong for one of them, which is
exactly the failure mode `contain-intrinsic-size` has when it is guessed: it is what
the scrollport measures an unrendered row as, so a wrong value makes the list's
`scrollHeight` wrong by that error for every unrendered row and the scrollbar thumb
drifts as you scroll.

### 4.1 Every declaration, and whether the element is actually animated

| Declaration | Selector | Value | Actually animated? | Verdict |
|---|---|---|---|---|
| `base.css:126` | `#visualizer-canvas, #home-visualizer-canvas` | `will-change: transform` (+ `transform: translateZ(0)` `:127`, `backface-visibility: hidden` `:128`) | Canvas pixels redrawn by `visualizer.js`; the element itself is not transformed | **Overridden by `:3033`** (`will-change: contents`, same specificity, later) — harmless dead entry |
| `base.css:3033` | `#visualizer-canvas, #home-visualizer-canvas` | `will-change: contents` | Yes — JS redraws the canvas 24–60×/s | **Correct** (`contents` does not itself force a layer; `translateZ(0)` does) |
| `base.css:1445` | `.particle` | `will-change: transform` | CSS animation exists (`particleFloat`, `:1444`) | **DEAD — 0 elements.** Whole block `base.css:1441–1452` (rule + `@keyframes`) is dead CSS |
| `base.css:3065` | `.settings-panels, .settings-nav, #search-results, .track-list` | `will-change: auto` | — | **Correct** — an explicit "flatten these" list (comment at `:3060`: "Avoid compositing ambiguity — flatten non-animated panels") |
| `base.css:3726` | `.aura-orb` | `will-change: transform` | Yes — `auraFloat`, 22/28/18 s infinite | **Correct** (3 elements) |
| `base.css:3705` | `.aura-orbs-container` | `contain: strict` | container of the 3 orbs, fixed `inset: 0` | **Correct** |
| `base.css:3725` | `.aura-orb` | `contain: strict` | size is explicit (`600/650/450` px at `:3737/3746/3756`) | **Correct** |
| `base.css:3723` | `.aura-orb` | `mix-blend-mode: normal` | — | Neutral; neutralised again at `:3732` under perf-low/battery |
| `base.css:459` | `#sidebar` | `contain: layout style` | static | **Correct** (contain is not a layer) |
| `base.css:536` | `#main-content` | `contain: layout` | static | **Correct, but with a side effect:** it makes `#main-content` the containing block for `position: fixed` descendants — notably `#lyrics-overlay` (`lyrics.css:239–243`, `position: fixed; inset: 0`), so the "fullscreen" lyrics overlay is actually sized to `#main-content`, not the viewport |
| `player-bar.css:27` | `#player-bar` | **`will-change: transform`** | **NO** — no CSS rule and no JS write ever transforms `#player-bar`. Its only transitions are `border-color 0.3s` / `transform 0.2s` (`:29`) and `button:active { transform: scale(0.9) }` (`:3375`) targets `button`, not `#player-bar` | **⚠ FLAG — permanent compositor layer for a static, full-width bar that additionally carries a live `backdrop-filter` (`visual-polish.css:98`) + a JS-updated `::after` (`player-bar.css:33–45`). A "will-change only on really animated elements" cleanup should remove this.** |
| `player-bar.css:28` | `#player-bar` | `contain: layout style` | static | Correct |
| `player-bar.css:43` | `#player-bar::after` | `will-change: opacity, transform` | Yes — orbit glow, driven from `player.js:1993–1994` at 30 fps | **Correct** (`display: none` under perf-low/battery, `:53–57`) |
| `player-view.css:37` | `.player-bg-glow-downscaled` | **`will-change: transform, opacity`** (+ `contain: strict` `:39`, `scale(1.1)` `:38`) | **NO** — the class is added once per track change (`player.js:1439`) and nothing animates it afterwards | **⚠ FLAG — this is the element with `filter: blur(50px)`, so the promotion keeps a ~10 %-oversized offscreen surface alive permanently** |
| `player-view.css:72` | `.player-glass-card::after` | `will-change: opacity, transform` | Yes — orbit glow | **Correct** |
| `player-view.css:57` | `.player-glass-card` | `contain: layout` | static | Correct |
| `lyrics.css:59` | `.lyrics-track, .player-lyrics-content, .lyrics-content, #lyrics-content, #overlay-lyrics-content` | `will-change: transform` (+ `translate3d` `:60`, `backface-visibility: hidden`) | Yes — `applyTransform()` writes `transform` on every position tick (`lyrics.js:465`) | **Correct** — this is the one genuinely transform-animated container |
| `lyrics.css:88` | `.lyric-line` | `will-change: auto` | — | Correct (resets the inherited hint) |
| `lyrics.css:138` | `.lyric-line.active` | `will-change: transform, filter` | Yes — `filter: blur(0)` at `:120` after `blur(2px)` at `:80` | **Correct** — exactly one `.active` line at a time |
| `lyrics.css:393/440/474` | perf-low / medium / battery / reduced-motion | `will-change: auto` | — | Correct (already handled) |
| `track-table.css:61` | `.track-item` | **`content-visibility: auto`** | Not animatable itself, but this is the app's only offscreen-culling mechanism | **Correct and load-bearing for §5** — with the caveat in §5.2 that it is not a substitute for DOM virtualisation |
| `track-table.css:62` | `.track-item` | `contain-intrinsic-size: auto 66px` | — | **Correct** — the row's real height is exactly 66 px: content `48` (`.track-cover-wrap` is `48×48`, `track-table.css:83–84`, the tallest child) + padding `8 × 2` (`track-table.css:34`) + border `1 × 2` (`track-table.css:36`) = **66 px**. `auto` makes it a placeholder until the row is first rendered, after which the real height replaces it, so the two agree and the scrollbar never moves. Derivation is restated in the comment at `track-table.css:42–59`. |
| `player-bar.css:423` | `#queue-drawer-content .track-item` | **`content-visibility: auto`** | — | **Correct** — the drawer row needs the same offscreen culling for the same reason |
| `player-bar.css:424` | `#queue-drawer-content .track-item` | `contain-intrinsic-size: auto 56px` | — | **Correct, and necessarily its own value**: the drawer shrinks the row to `6 px` padding and a `42 px` cover ⇒ `42 + 6 + 6 + 1 + 1` = **56 px**. Inheriting the table's `66 px` would overstate every skipped row by 10 px and make the drawer's scrollbar drift while it is open. It also keeps the drag-and-drop honest: the drag handlers read `getBoundingClientRect()` (`queue.js:237`, `:258`), which for a skipped row returns the intrinsic-size box rather than the real one. Derivation is restated in the comment at `player-bar.css:408–422`. |

### 4.2 Animated but missing `will-change`

| Element | Animated by | `will-change`? |
|---|---|---|
| `.pb-cover.spinning` | `player-bar.css:93` `spinDisc 12s linear infinite` | **No** |
| `.spinner`, `.animate-spin`, `.animate-spin-slow`, `.shimmer-bg`, `.skeleton*`, `.ui-shimmer` | `base.css:1463/1464/1486/1537/1995/3380`, `home-view.css:490`, `visual-polish.css:173`, `tokens.css:136` | **No** — correct; these animate `background-position`/`opacity`, which `will-change` does not accelerate |
| `.track-item` `fadeIn` | `track-table.css:63` | **No** — correct; `content-visibility: auto` already implies containment, and a permanent `will-change` on 2000 rows would be catastrophic |

**Net: of 15 `will-change` declarations, 2 are wrong (`player-bar.css:27`,
`player-view.css:36`), 1 is dead (`.particle`), 1 is overridden (`base.css:125`),
and 11 are justified.**

---

## 5. Long list rendering

### 5.1 Is there virtualization? **No.**

`ui/web_new_v2/js/library.js`:
* `LIB_BATCH_SIZE = 50` — **line 372**
* `makeLibraryBatchRenderer()` — **lines 375–388**: appends 50 rows per call, then `renderIcons()` (line 384)
* `attachLibraryScrollLoader()` — **lines 391–416**: finds the scroll parent by walking ancestors and calling `getComputedStyle(node)` (line 394); drains batches while the content does not overflow, **max 20 extra batches** (lines 403–406); then a `{passive:true}` `scroll` listener appends another 50 whenever within 200 px of the bottom (lines 408–413)
* `renderLibraryList()` — **lines 418–424**: clears the container, renders the first 50, attaches the loader

So a 2000-track library **eventually renders all 2000 rows** by scrolling. There is
no row recycling, no windowing, no `IntersectionObserver`-based unmount.

### 5.2 Is `content-visibility` used? **Yes — twice, on the two row geometries, and it is the only mitigation in place.**

`css/components/track-table.css:61–63`:
```css
.track-item {
    content-visibility: auto;
    contain-intrinsic-size: auto 66px;
    animation: fadeIn 0.3s ease forwards;
}
```
and `css/components/player-bar.css:423–424`:
```css
#queue-drawer-content .track-item {
    content-visibility: auto;
    contain-intrinsic-size: auto 56px;
}
```
The two intrinsic sizes differ because the drawer row is a different height
(56 px, §4.1); they are not two copies of the same declaration.

**What this does and does not buy — read this before treating §5.3 as fixed.**
`content-visibility: auto` makes the browser skip layout, paint and style work for
subtrees that are off-screen. It is a *rendering* optimisation and nothing else. It
does **not** reduce:

* **DOM node count.** The row and its ~37 descendants exist in the document either
  way. `content-visibility` culls what is painted, not what is parsed.
* **Memory.** Node objects, their attributes and their retained closures are all
  still allocated.
* **Listener count.** All 7 listeners per row (§5.4) are still registered and still
  retain their `track` object.
* **Construction cost.** The 76 000 nodes of §5.3 are still built, still appended,
  and `renderIcons()` still walks them.

By this document's own measurement that is ~38 DOM nodes per row, i.e. **~76 000
nodes** for a 2 000-track library, with 14 000 listeners attached to them.

**The real fix for long lists is DOM-node virtualisation** — windowed rendering with
row recycling, so that only the rows near the viewport exist as nodes at all (the
usual shape here: an `IntersectionObserver`- or scroll-driven window with a spacer of
the right total height above and below, plus a single delegated listener per event
type on the list container instead of 7 closures per row). That is what actually
attacks node count, memory and listener count. `content-visibility` is worth keeping —
it is correct, it is cheap, and it does reduce layout/paint/style work for the long
list — but it is a complement to virtualisation, not a substitute for it, and no
measurement in this document shows it reducing any of the three costs above.

### 5.3 How many DOM nodes does a 2000-track library create? **MEASURED: 76 000.**

`tools/bench/track_row_nodes.js` extracts the real template literal from
`js/utils.js` (`createTrackElement`, **lines 338–368**), substitutes the
runtime-equivalent output of `getCoverUrl` / `getSourceIcon` / `formatArtistNames` /
`formatTime`, counts element nodes with a tag scanner, then expands each
`<i data-lucide="X">` using the **real `ICONS` map read out of the shipped
`js/lucide.min.js`** (101 icons). The run asserts `leftover_template_holes: []`, so
no `${...}` was missed.

| Variant | Authored elements | `data-lucide` icons in the row | Lucide adds | **Nodes per row** | **× 2000 tracks** |
|---|---|---|---|---|---|
| minimal (no cover, no source badge, downloaded → `check`) | 23 | `play` 2, `check` 2, `heart` 2, `plus` 3, `more-horizontal` 4 | +8 | **31** | **62 000** |
| **typical library row** (proxied cover, `youtube` badge, `download` icon) | 26 | `play` 2, `youtube` 3, `download` 4, `heart` 2, `plus` 3, `more-horizontal` 4 | +12 | **38** | **76 000** |
| multi-artist row (2 `.clickable-artist` spans) | 27 | as above | +12 | **39** | **78 000** |

Per-row tag histogram (typical): `div` 8, `button` 4, `svg` 1, `path` 1,
`circle` 2, `img` 1, `i` 6 → 25 authored + `div.track-item` root = 26.

### 5.4 Event listeners created by that list: **MEASURED 14 000.**

`createTrackElement` registers **7** listeners per row
(`js/utils.js:371` click, `:387` download, `:415` artist — one **per artist span**,
`:435` like, `:480` add, `:492` more, `:500` contextmenu).
2000 rows × 7 = **14 000 listeners**, all closures retaining the whole
`track` object and the whole `tracksArray`.

### 5.5 O(n) / O(n²) work in the render path

| Complexity | file:line | Work |
|---|---|---|
| **O(n) per batch, whole-document** | `js/library.js:384` | `renderIcons()` is called with **no argument**, so `utils.js:562` uses `root = document.body` and lucide does `document.querySelectorAll('[data-lucide]')` over the **entire document**. For 2000 rows that is **40 whole-document queries** (2000 / 50). It does not re-render already-converted icons (lucide's `renderElement` does not re-add `data-lucide`), so each pass only converts the new batch — but the *scan* is still full-document. |
| **O(n) per row, whole-document** | `js/library.js:381` | `getCurrentTrack()` is evaluated **inside** the loop for every row. It is `return currentTrack` (`player.js:570`), so cheap — but it is a call in the innermost loop. |
| **O(n) whole-document on track change** | `js/utils.js:301–305` | `updatePlayingTrackInDOM()` does `document.querySelectorAll('.track-item')` over **every** track row in the document and runs `isSameTrack()` on each. Reached from `js/utils.js:588` (`nedotify:track_changed`) and `js/player.js:1281`. With 2000 rows this is a 2000-element sweep + 2000 comparisons on every track change. |
| **O(n²) — NOT present** | `js/library.js:485–492`, `:523–531`, `:563–572` | Dedup uses `Set`, not `Array.includes`. `player.js:1168` (`queueIds.includes(k1)`) is O(queue) inside a 6-element filter — bounded and irrelevant. |
| **O(ancestors × getComputedStyle)** | `js/library.js:394` | `getComputedStyle(node)` while walking up from the container looking for the scroll parent. Once per `attachLibraryScrollLoader` call, depth ≈ 5. Cheap, but it is a forced style flush. |
| **O(n) forced layout during initial drain** | `js/library.js:403` | `scrollParent.clientHeight >= scrollParent.scrollHeight` in a loop, up to 20 iterations — each read after the previous `renderNext()` wrote 50 rows ⇒ **20 forced synchronous layouts** during the initial drain. Combined with the loop above, that single turn builds up to **1 050 rows / ~39 900 nodes / 7 350 listeners** before the first paint. |
| **O(n) per scroll event, unthrottled** | `js/library.js:408–413` | 3 layout reads per `scroll` event; `{passive:true}` but no throttle/rAF coalesce. |
| **O(n) list rebuild** | `js/library.js:646`, `js/library.js:798`, `js/library.js:452` | `document.querySelectorAll('.lib-playlist-item')` / `[...list.children].indexOf(item)` per interaction. Bounded by playlist count, not library size. |
| **O(n) staggered animations** | `js/utils.js:651` + `track-table.css:63` | `item.style.animationDelay = ${Math.min(index*0.03, 0.5)}s` — one `fadeIn` per row, so 1 050 in the first turn and 2 000 in total. |
| **O(n) per track change in search** | `js/search.js:661`, `:855` | Album/playlist detail views use `tracksContainer.appendChild(createTrackElement(...))` in a bare loop — **no batching at all**, so a 500-track playlist creates 500 rows in one synchronous pass, unlike the library's 50-row batching. |

---

## 6. Image loading

### 6.1 Every image-element creation site (MEASURED)

**12 literal `<img …>` template sites** (`frontend_hotspots.json` →
`section6_images.img_sites`), plus **2 `document.createElement('img')`** and
**2 `new Image()`** — 16 image-element creation sites in total.

| file:line | Site | `loading="lazy"` | `decoding="async"` |
|---|---|---|---|
| `js/utils.js:341` | **track row cover** (library / search / queue / profile) | **yes** | **no** |
| `js/utils.js:168` | `buildSafeImgTag()` helper | yes | no |
| `js/utils.js:230` | `.pl-collage-cell` (playlist collage) | yes | no |
| `js/utils.js:721` | `.rich-menu-cover` (context-menu header) | **no** | no |
| `js/queue.js:148` | queue drawer row cover | yes | no |
| `js/artist_profile.js:505` | album item cover | yes | no |
| `js/settings.js:2864` | `.workshop-card-media` | yes | no |
| `js/search.js:405` | search result cover | **no** | no |
| `js/search.js:515` | album grid cover | **no** | no |
| `js/search.js:619` | album modal cover (110 px) | **no** | no |
| `js/search.js:700` | playlist modal cover | **no** | no |
| `js/search.js:810` | playlist card cover (110 px) | **no** | no |

**Split: 6 with `loading="lazy"`, 6 without.** The 6 without are
`utils.js:721` (context-menu header) and all five `search.js` album/playlist
card + modal covers. The last two are **eager**: a 40-album modal fires 40
requests on open.

Non-literal creations:

| file:line | Site | `loading`/`decoding` |
|---|---|---|
| `js/home.js:732` | `document.createElement('img')` — artist avatar | none set; `src` assigned in JS |
| `js/artist_profile.js:304` | `document.createElement('img')` — artist avatar | none set |
| `js/player.js:1441` | `new Image()` — offscreen pre-decode of the cover art for `#player-bg-glow` | n/a (detached) |
| `js/utils.js:535` | `new Image()` — background-image downscale before persisting | n/a (detached) |

Static `<img>` in `index.html` (7 sites: 3× `logo.png`, plus the 4 empty
`src=""` cover slots `#mp-cover`, `#pp-cover`, `#pb-cover`,
`#profile-avatar-img`, and the inline-SVG `#modal-et-cover-img`) — none carry
`loading` or `decoding`.

**`decoding="async"` appears 0 times in the entire frontend (MEASURED).**

### 6.2 How many cover images would a 2000-track library request at once?

* Track rows carry at most **one `<img>` each** (`utils.js:341`) → **2000 image
  elements**, one per row.
* They carry `loading="lazy"`, so the *initial* concurrent request burst is bounded
  by the Chromium lazy-load distance heuristic rather than by 2000. In practice that
  is roughly one to three viewport heights of rows, i.e. **~30–80 requests**, not 2000.
* **But the elements themselves are all created at once**, so 2000 `<img>` elements
  (each with an `onerror` inline attribute and a `display:none` fallback path) sit in
  the DOM, and every row that scrolls into view later issues a fresh request.
* The other 5 `loading="lazy"`-less **literal** sites (`search.js:405/515/619/700/810`)
  are album/playlist cards and modals and are **eager**: an album modal with 40 albums
  fires 40 requests on open.

### 6.3 What is the `src`? Local proxy or remote?

`js/utils.js:236–268 getCoverUrl()` — three outcomes, in order:

1. **`./covers/<name>`** (relative, `utils.js:243–246`) when `cover_path` contains
   `web_new_v2/covers/`. Served by the app's own static file server — **same origin,
   cheapest case**.
2. **`http://127.0.0.1:<PROXY_PORT>/api/cover?path=<encoded>&k=<token>`**
   (`utils.js:247–250`). This is the **loopback HTTP proxy**, not a static file:
   `core/proxy.py:652` routes `/api/cover` → `_safe_cover_path()` (`:255`, roots
   from `_cover_roots()` `:123` = `~/.nedotify/covers`, `~/.nedotify/avatars`, and
   `ui/web_new*/covers` when present) → `serve_local_file()`.
   The server is `ThreadingHTTPServer` (`core/proxy.py:364–383`, `daemon_threads = True`,
   bound to `127.0.0.1:0` at `:1175`), so each cover is a **thread + a realpath +
   a file read**. 2000 covers = 2000 loopback HTTP requests.
3. **Remote URL** — `utils.js:257–267`: `track.cover_url || track.og_image ||
   track.artwork_url`, prefixed with `https://` if schemeless, with `%%` →
   `400x400` and a Yandex size rewrite. **For any track that only has a provider
   `cover_url`, the browser goes to the internet.**
4. `''` when `cover_path` exists but `window.PROXY_PORT` is not yet known
   (cold start) — callers keep their gradient fallback, and the collage retries at
   3 s (`js/home.js:651`).

`window.PROXY_PORT` / `window.PROXY_TOKEN` come from `core/api.py:1038
get_proxy_info()` (`{port, token}`).

**Implication:** for a locally-indexed library every cover costs one loopback HTTP
request through a Python `ThreadingHTTPServer`. `get_proxy_info` is also the reason
`library.js:2363`-style cold-start behaviour produces no cover images at all on the
first paint.

---

## 7. Animation / transition inventory — the visual-guard baseline

There are two artefacts here and they have different jobs. They must not be merged:
the guard's keying deliberately excludes line numbers, and the reporting artefact's
keying is built on them.

### 7.0 The two artefacts

**`tools/bench/results/animation_declarations.json` — the ENFORCED baseline**

| Property of the artefact | Value |
|---|---|
| Schema | `nedotify.animation-declarations.v2` |
| Generated by | `tools/visual_guard/run_guard.py --write-css-baseline` |
| Scanned | `ui/**` with the suffixes `.css`, `.html`, `.js` (inline styles and `style.cssText` assignments included) |
| Keying | **`<relative/path>|<property>` → multiset of normalised values.** No line numbers anywhere, by design. |
| Records | 651 declarations across 99 keys in 24 files (re-record with the command above) |
| Read by | `css_declaration_guard()` — `ok = not changed and not removed`; additions are reported but allowed |

Why there are no line numbers: the original key was `<file>:<line>:<text>` and `ok`
was computed over the key intersection alone. Inserting or deleting one line shifted
every later key, the intersection collapsed to the empty set, and the guard passed
**vacuously** — measured on a clean tree: baseline 296 / current 745 / intersection 0
/ `ok` True. A list of values per key is position-independent by construction, so
reordering or moving a declaration reads as no change while deleting one of two
identical declarations still reads as a removal.

**`tools/bench/results/animation_declarations_inventory.json` — the LINE-ACCURATE REPORT**

This is what the counts in §7.1 below come from. It is written by
`tools/bench/css_inventory.py`, which parses only `ui/web_new_v2/css` (not JS, not
HTML), so it is a *different and smaller* population than the guard's 651.

| Property of the artefact | Value |
|---|---|
| Schema | `nedotify.animation-declarations.v1` |
| Generated by | `tools/bench/css_inventory.py` |
| Root | `ui/web_new_v2/css` (the 10 files in `styles.css`'s `@import` chain, plus `styles.css` itself) |
| Sort key | `(file, line, selector, property, value)` — declared in the file as `sort_key` |
| Every record carries | `key` (`file:line:selector|property|value`), `file`, `line`, `selector`, `at_rules`, `property`, `value`, `important`, `kind`, `cascade_index` |
| **Total guard declarations** | **302** — snapshot recorded 2026-10-06; regenerate with `tools/bench/css_inventory.py` |
| Total declarations parsed | **4 232** (`declaration` 4 160, `keyframe-step` 63, `at-rule` 9, `nested-rule` 0) — **the CSS is still being edited, so treat this as needing a final regeneration rather than a fixed figure** |
| Determinism | sorted by `sort_key`, so byte-stable across runs |
| Note | `counts.by_kind` counts *every* declaration the parser saw, not just the guarded ones — it does not equal `len(declarations)` and is not meant to |

The two counts therefore answer different questions and must not be added or
compared: **651** is what the guard protects across all of `ui/**`, **302** is what
the CSS-only reporting scan enumerates.

### 7.1 Guard property coverage

Counted by the CSS-only reporting scan (see §7.0 for why this is a different
population from the enforced baseline). Every declaration whose property is in this
set is captured, with duplicates preserved so a changed value is always visible:

```
transition, transition-property, transition-duration, transition-delay,
transition-timing-function,
animation, animation-name, animation-duration, animation-delay,
animation-iteration-count, animation-timing-function, animation-direction,
animation-fill-mode, animation-play-state,
backdrop-filter, -webkit-backdrop-filter, filter, -webkit-filter,
will-change, contain, contain-intrinsic-size, content-visibility,
mix-blend-mode, perspective, backface-visibility
```

| Property | Count | | Property | Count |
|---|---|---|---|---|
| `transition` | 138 | | `will-change` | 15 |
| `backdrop-filter` | 34 | | `contain` | 7 |
| `animation` | 34 | | `animation-duration` | 3 |
| `-webkit-backdrop-filter` | 28 | | `animation-play-state` | 2 |
| `filter` | 18 | | `backface-visibility` | 2 |
| `@` (the 9 `@import` lines) | 9 | | `mix-blend-mode` | 2 |
| `animation-delay` | 4 | | `transition-duration` | 1 |
| `-webkit-filter` | 1 | | `content-visibility` | **2** |
| | | | `contain-intrinsic-size` | **2** |

Snapshot of `counts.by_property` in
`animation_declarations_inventory.json`, read **2026-10-06**. These are counts of the
CSS-only reporting scan, not of the enforced baseline — re-run
`tools/bench/css_inventory.py` and read the new `counts.by_property` for a current
figure. The two `content-visibility` and two `contain-intrinsic-size` entries are the
two row geometries of §4.1.

### 7.2 What the guard does and does not cover

**Covered:** every blur radius, every `saturate`/`brightness` filter function, every
duration, delay, iteration count, easing function, `will-change`, `contain`,
`content-visibility`, `transition` property list, and every `@keyframes` step. The v2
baseline additionally covers **the custom properties those values consume** — see the
caveat below, which is now closed rather than open.

**Not covered (and therefore free to change):** colours, radii, spacing, fonts,
layout, `box-shadow`, `opacity`, `z-index`.

**Caveat on blur tokens — closed in v2.** An earlier version of this document flagged
a real gap: rules are written as `backdrop-filter: blur(var(--blur-md))`, so recording
only the literal text would show no diff when someone changed `--blur-md` in
`tokens.css`, even though the rendered radius would change. The v2 baseline records
`--blur-*`, `--glass-blur`, `--app-bg-opacity`, `--player-glow-*`, `--glow`,
`--transition`, `--anim`, `--ease`, `--dur` and `--duration` as guarded keys in their
own right (`WATCHED_VARS` in `run_guard.py`), across `.css`, `.html` and `.js`. So
moving `--blur-md` from `8px` to `6px` *is* now a diff, whether it is edited in
`css/tokens.css`, in `css/themes.css`, or from JS — the two JS writers of those tokens
are `js/main.js:191–321` (`restorePreferences`, at module eval) and
`js/settings.js:144–152` (`slider-glass-blur`), and both are inside the scanned set.
What remains uncovered is any custom property that feeds a guarded value but does not
match one of those prefixes.

---

## 8. TOP-10 ranked hot spots

Impact = expected cost of the operation on the Chromium/WebView2 compositor or main
thread, given a 2000-track library on a 1920×1080 window. Every row states its
evidence and whether it is **MEASURED** or **STATIC**.

| Rank | Hot spot | Evidence | Type |
|---|---|---|---|
| **1** | **`#main-content` is a full-bleed `backdrop-filter` root, and 13 of the 50 active backdrop-filters are nested inside it** — including a **3-deep chain** (`#main-content` 8 px → `#view-settings.settings-overlay` 16 px → `.settings-modal-card` 32 px). Every repaint of the settings view re-samples a ~1 550×830 px surface three times, the innermost and largest-radius blur transmitting only 12 %. | 50 active `backdrop-filter` declarations; 13 nested; max measured nesting depth 1 ancestor-chain / 3 filters (`backdrop_nesting.json` → `counts.max_nesting_depth`); radii 8/16/32/40 px. | MEASURED count + STATIC verdict |
| **2** | **76 000 DOM nodes for a 2000-track library, with no virtualization.** 38 nodes/row × 2000; `content-visibility: auto` reduces render work but not node/memory/listener cost. | `tools/bench/track_row_nodes.json` → `library_scenarios.typical_library_row = {nodes_per_row: 38, nodes_for_2000_tracks: 76000}`, derived from the real template + the real lucide `ICONS` map, with `leftover_template_holes: []`. | **MEASURED** |
| **3** | **`lyrics.js:1113 window mousemove` reads `offsetWidth`/`offsetHeight` and writes `style.left`/`style.top` in the same handler**, with no `passive`, no throttle and no rAF coalesce — one forced synchronous layout per `mousemove` during a PiP-widget drag. | `js/lyrics.js:1077–1096`; listed first among the 10 global layout-thrash candidates. | STATIC (verified by reading) |
| **4** | **`lyrics.css:245 #lyrics-overlay` applies `blur(40px)` — the largest radius in the app — over its own `rgba(14,7,17,0.88)` background**, nested inside `#main-content`'s 8 px blur. 12 % transmission. Same shape for `.settings-modal-card` (32 px @ 0.88), `#mini-player-overlay` (24 px @ **0.96**), `#search-platform-dropdown` (16 px @ **0.96**), `#custom-context-menu` (20 px, dead), `.search-suggestions-dropdown` (20 px @ 0.94), `.custom-glass-dropdown-menu` (16 px @ 0.95). | 11 "do not blur under an opaque layer" sites tabulated in §3.3, each with the element's own background alpha read from its CSS rule. | STATIC alpha + MEASURED radii |
| **5** | **`initParticles()` leaks 4 `window` listeners on every call, and it is called from 3 unthrottled slider `input` handlers.** Dragging `slider-particles-count` 30→80 ≈ 50 `input` events ≈ 50 calls ≈ **+50 `resize`, +50 `mousemove`, +50 `mouseleave`, +50 `mini_player_toggled` listeners**, plus 50 full particle-array rebuilds — and `window mousemove` is a hot path. | `js/particles.js:263–305` (`removeEventListener` called with the freshly-created closure); 8 call sites (`settings.js:124,129,134,202,614,689,1315` + `main.js:470`); `settings.js:643–646` fires `onChange` on every `input`. | STATIC |
| **6** | **A single synchronous turn can create up to 1 050 rows — ~40 000 DOM nodes, 7 350 event listeners, 1 050 `<img>` elements and 1 050 staggered CSS animations — before the browser gets a chance to paint.** `renderLibraryList` renders 50, then `attachLibraryScrollLoader`'s drain loop (`library.js:403–406`) runs up to 20 more `renderNext()` calls in the same synchronous turn: `50 + 20 × 50 = 1 050` rows. Scrolling to the end takes the total to 2 000 rows / 76 000 nodes / 14 000 listeners. | `js/library.js:372` (batch size 50) + `:403` (`guard < 20`) ⇒ 1 050 rows/turn; × 38 nodes = 39 900; × 7 listeners = 7 350. Each row also sets `item.style.animationDelay` (`utils.js:313`), feeding `track-table.css:44`. | **MEASURED** (node/icon counts) + STATIC (listener count, drain arithmetic) |
| **7** | **`renderIcons()` with no argument scans the whole document on every 50-row batch** (`root = document.body` → `document.querySelectorAll('[data-lucide]')`) → **40 full-document queries** for a 2000-track library. Same pattern at 55 call sites app-wide. | `js/library.js:384` + `js/utils.js:560–574`; `grep '\brenderIcons\s*\('` = **55 call sites**; `library.js:372` batch size 50 → 2000/50 = 40 batches. | MEASURED count + STATIC |
| **8** | **`updatePlayingTrackInDOM()` runs `document.querySelectorAll('.track-item')` + `isSameTrack()` over every row in the document on every track change** — a 2000-element sweep plus 2000 comparisons, twice-reachable (`utils.js:588` and `player.js:1281`). | `js/utils.js:296–306`; `isSameTrack` at `utils.js:279–294`. | STATIC |
| **9** | **`.player-bg-glow` runs `filter: blur(50px)` (the app's largest radius) on a ~420 px × viewport element, promoted permanently by `will-change: transform, opacity` + `contain: strict` + `scale(1.1)` — and it is never animated.** Offscreen surface is kept ~10 % larger than needed for the whole session. | `css/components/player-view.css:26–40`; `--ambient-blur: 50px` (`tokens.css:66`); class added once per track change at `js/player.js:1439`. | STATIC |
| **10** | **`animateProgress` re-arms itself while `document.hidden`** (`player.js:1067`), so it is the one loop in the app that is **not** pausable as written; and two module-level `window resize` handlers run unthrottled full-document queries on every resize event (`player.js:1763` `querySelectorAll('.waveform-canvas')`, `visualizer.js:117` canvas resize). | `js/player.js:1066–1069`, `:1763–1768`; `js/visualizer.js:108–117`. Compare the correct pattern at `particles.js:263–267` (100 ms debounce) and `player.js:2051–2061` (rect cached on `mouseenter`, rAF-coalesced redraw). | STATIC |

### Runners-up worth recording (not in the top 10)

* `#player-bar` carries `will-change: transform` while nothing ever transforms it, **and** a live `backdrop-filter` **and** a JS-updated `::after` — one of only two unjustified `will-change` declarations (`player-bar.css:27`).
* A `document`-level `{ passive: false }` `wheel` listener (`main.js:562`) forces the compositor to wait on the main thread for every wheel event app-wide.
* `utils.js:693` registers `window scroll` with `capture: true` — fires for every scroll event of every scrollable in the document while a context menu is open.
* Dead CSS that hides real work: `.particle` (+ `@keyframes particleFloat`), `.track-equalizer-bars .eq-bar` (+ `@keyframes eqPulse`), `#custom-context-menu`, `.card` — 0 elements each. `.card`'s absence also silently reduces `efficiency.js:6`'s IntersectionObserver to 3 live selectors.
* 2 infinite CSS animations on dead selectors, 1 dead `will-change`, 1 overridden `will-change`.
* `search.js:661` / `:855` render album and playlist detail lists in a **bare loop with no batching at all** — unlike the library's 50-row batches.

---

## 9. Files written by this pass

New files only, all inside the permitted directories:

```
tools/bench/css_inventory.py                       (new)
tools/bench/dom_nesting.py                         (new)
tools/bench/js_census.py                            (new)
tools/bench/build_hotspots.py                       (new)
tools/bench/track_row_nodes.js                      (new)
tools/bench/lucide_node_count.js                    (new)
tools/bench/verify_frontend_report.py               (new — the gate for this document)
tools/bench/results/animation_declarations.json    (new — the ENFORCED visual-guard
                                                    baseline, v2, line-number-free)
tools/bench/results/animation_declarations_inventory.json
                                                   (new — the LINE-ACCURATE report, v1)
tools/bench/results/css_blur_map.json               (new)
tools/bench/results/backdrop_nesting.json           (new)
tools/bench/results/track_row_nodes.json            (new)
tools/bench/results/frontend_hotspots.json          (new — run build_hotspots.py last)
docs/perf/prof_frontend.md                          (new — this document)
```

No existing project file was modified, nothing was committed, and the pytest suite
was not run. The six in-flight files (`js/lyrics.js`, `css/components/lyrics.css`,
`index.html`, `css/components/player-view.css`, `services/youtube_service.py`,
`services/soundcloud_service.py`) were read only; findings that concern them are
reported here (notably rank 3 above and `lyrics.css:245` in §3) and must be applied
by whoever owns that work.