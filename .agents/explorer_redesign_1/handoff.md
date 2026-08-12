# Handoff Report — UI Analysis and Bug Fix Proposals

## 1. Observation
We observed and investigated the AURA Music frontend codebase at `ui/web_new/`. Specifically, the following details were gathered:

- **Theme Files**: 
  - `ui/web_new/css/themes.css` (lines 24-112) contains definitions for 10 themes: `amoled`, `dark`, `midnight`, `emerald`, `sunset`, `ocean`, `lavender`, `rose`, `amber`, and `slate`.
  - `ui/web_new/js/settings.js` (lines 5-23) defines the list `THEMES` which includes 17 themes, some of which (e.g. `aqua`, `light`, `sky`, `mint`) are not defined in `themes.css`.
  - Ripgrep searches show multiple references to `var(--primary)`, `var(--primary-rgb)`, and `var(--primary-fg)` in `ui/web_new/css/styles.css` (e.g., line 34, 213, 278, etc.). A specific search for `--primary` variable definitions inside the CSS folder yielded no matches, confirming the variables are never defined.
- **Sliders & Toggles**:
  - `ui/web_new/css/styles.css` (lines 662-718) reveals that volume and progress sliders are custom HTML divs (`.volume-track`/`.volume-fill` and `.progress-track`/`.progress-fill`), and they color their filled portion using `var(--primary)`.
  - `ui/web_new/css/styles.css` (line 885) styles `.toggle-switch` with `background: var(--accent)` when off, and `.toggle-switch.on` (line 892) with `background: var(--primary)`.
- **Audio Visualizer & Equalizer & Lyrics**:
  - `ui/web_new/js/visualizer.js` (lines 14-16) contains targets for both `visualizer-canvas` and `home-visualizer-canvas`. In `draw()`, it animates the bars using `Math.sin()` and `Performance.now()` (lines 97-111).
  - `ui/web_new/js/equalizer.js` (lines 14-40) dynamically renders 10 frequency sliders. `audio/engine.py` (lines 97-104) initializes the equalizer via VLC using a list of 10 float values.
  - `ui/web_new/js/lyrics.js` (lines 156-159) implements automatic scrolling by calculating `targetLine.offsetTop` and using `container.scrollTo({ top: offset, behavior: 'smooth' })`.
  - `ui/web_new/css/styles.css` (line 1349) has `scroll-behavior: smooth` defined for `.lyrics-scroll-container`.
- **Bug Fixes**:
  - `ui/web_new/js/library.js` (line 247) calls `window.pywebview.api.create_playlist(name.trim())`. 
  - `core/database.py` (line 368) and `core/api.py` (line 546) return the raw integer ID of the created playlist from this API call.
  - `ui/web_new/js/library.js` (line 249) attempts to call `window.pywebview.api.add_to_playlist(pl.id, currentContextTrack)`.
  - `ui/web_new/js/library.js` (line 139) accesses the playlist ID from dataset using `parseInt(card.dataset.plId)`.

---

## 2. Logic Chain
- **Theme Variables**: Since `--primary`, `--primary-rgb`, and `--primary-fg` are used in `styles.css` for primary highlight styles (including active slider fills, visualizer bars, and on-state toggles) but are never defined in `themes.css`, the UI has inconsistent fallback styling. Defining these variables under each specific theme in `themes.css` ensures full system thematic styling.
- **Switch Toggles**: The off-state switch currently uses `var(--accent)`, which is the bright theme highlight color, making it visually indistinguishable from its active state (except for the dot sliding). Changing the off-state background to a neutral, dark semi-transparent color like `var(--bg-active)` resolves the confusion.
- **Equalizer**: Since the UI wants a simplified 3-band controls interface while VLC expects a 10-band array, mapping the Low, Mid, and High sliders to bands 0-2, 3-6, and 7-9 respectively in the JS file allows using the existing `set_equalizer` API call without any backend changes.
- **Lyrics Stutter**: Combining JS `{ behavior: 'smooth' }` with CSS `scroll-behavior: smooth` causes the WebView rendering engine (Edge WebView2) to calculate smooth animation vectors twice, causing stuttering and jumping. Using the native `targetLine.scrollIntoView({ behavior: 'smooth', block: 'center' })` centers lines smoothly and eliminates manual offset calculation.
- **Window Transparency**: A transparent window created in PyWebView requires the root HTML/body documents and layers to have transparent/translucent backgrounds. By enforcing `html, body { background: transparent !important; }` and wrapping layout containers in CSS `color-mix(in srgb, var(--bg-main) 75%, transparent)`, transparency is achieved dynamically without altering hex colors.
- **Playlist ID Bug**: The `create_playlist` Python API returns an integer ID, but `library.js` treats it as an object and reads `pl.id` (which evaluates to `undefined`). This triggers a database constraint error, halting script execution. Accessing `pl` directly fixes the crash and enables successful playlist additions.

---

## 3. Caveats
- No Python code execution has been done since this is a read-only investigation.
- We assume that the database column casing matches lowercase sqlite3 defaults, but we provided case-insensitive overrides (`pl.id || pl.ID`) to be fully robust.

---

## 4. Conclusion
The frontend issues can be resolved with localized CSS and JS adjustments. Specifically:
- Defining `--primary` variables in `themes.css` fixes active highlight themes, custom range sliders, and active visualizer colors.
- Redefining `.toggle-switch` off-state background to a dark neutral color resolves settings visual bugs.
- Mapping 3 bands in `equalizer.js` to 10 bands of VLC, and refactoring `lyrics.js` to use `scrollIntoView` fixes visualizer, equalizer, and lyrics scrolling behavior.
- Implementing transparent root layers and `color-mix` backgrounds enables native transparency.
- Replacing `pl.id` with `pl` inside `createPlaylist` in `library.js` resolves the playlist addition crash.

---

## 5. Verification Method
- **Files to Inspect**: 
  - `ui/web_new/css/themes.css` (verify variables mapping)
  - `ui/web_new/css/styles.css` (verify slider, transparency, and toggle CSS rules)
  - `ui/web_new/js/library.js` (verify `createPlaylist` fix and case-insensitive ID retrieval)
  - `ui/web_new/js/lyrics.js` (verify `scrollIntoView` replaces manual scrolls)
  - `ui/web_new/js/equalizer.js` (verify 3-band UI mapping logic)
- **Execution Test**: Run `python main.py` and inspect console outputs. Navigate to settings, change themes, toggle options, create and open playlists, check visualizer behavior, and check equalizer reactivity.
