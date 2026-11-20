## AREA WN-33 — UI styling: themes, tokens, component CSS, legacy CSS pack — ROLE B

### 1. Scope reviewed

**Files opened (path: line ranges actually read)**

| Path | Lines read |
|---|---|
| `docs/audits/WIN_AUDIT_CONTEXT.md` | 1–200 (whole) |
| `docs/audits/WIN_AUDIT_AREAS.md` | 1–70 (whole) |
| `ui/web_new_v2/index.html` | 1–120 (head: CSP + all 25 `<link>` tags), 1944 (`default_cover.png`) |
| `ui/web_new_v2/css/tokens.css` | 1–180 (whole) |
| `ui/web_new_v2/css/themes.css` | 1–422 (whole) |
| `ui/web_new_v2/css/fonts.css` | 1–99 (whole) |
| `ui/web_new_v2/css/styles.css` | 1–69 (whole) |
| `ui/web_new_v2/css/components/base.css` | 1–320, plus targeted reads at 862–891, 3040–3099, and a full selector/declaration scan of all 4,633 lines |
| `ui/web_new_v2/css/components/home-refresh.css` | 1–249 (whole) |
| `ui/web_new_v2/css/components/window-resize.css` | 1–34 (whole) |
| `ui/web_new_v2/css/components/ui-style-picker.css` | 1–32 (whole) |
| `ui/web_new_v2/css/components/{player-bar,player-view,lyrics,home-view,track-table,search-refresh,library-refresh,settings-refresh,onboarding,profile-refresh,downloads-view,smart-playlists,feature-tools,visual-polish}.css` | full machine scan (selectors, declarations, `!important`, `url()`, `backdrop-filter`, `will-change`, raw colours) + targeted reads of every `backdrop-filter` / `filter: blur()` / `will-change` site |
| `ui/MACos_ui/tokens.css` | 1–119 (whole) |
| `ui/MACos_ui/interface.css`, `settings.css`, `library.css` | full machine scan + targeted reads of every `url()`, `backdrop-filter`, `filter: blur()` site |
| `ui/web_new_v2/assets/backgrounds/SOURCES.json` | 1–141 (whole) |
| `ui/web_new_v2/js/appearance-assets.js` | 1–51 (whole) |
| `ui/web_new_v2/js/settings-view.js` | 1–123 (whole) |
| `ui/web_new_v2/js/settings.js` | 1–80, 485–604, 2760–2839, 3100–3209 |
| `ui/web_new_v2/js/efficiency.js` | 1–192 (whole) |
| `ui/web_new_v2/js/particles.js` | 292–321 |
| `ui/web_new_v2/js/main.js` | grep + 1–120, 320–399, 415–484 |
| `ui/web_new_v2/js/ui-style.js` | grep only (macOS pack toggle) |
| `core/ui_assets.py` | 1–22 (whole) |
| `main.py` | 55–104, 320–399, 415–484 |
| `setup_pyinstaller.spec` | grep (datas) |
| `installer.iss` | 1–92 (whole) |
| `tests/test_frontend_css_wiring.py` | 1–184 (whole) |
| `tests/test_visual_guard_css_decls.py` | 1–570 (whole) |
| `tests/test_visual_guard_diff.py` | 1–133 (whole) |
| `tools/visual_guard/run_guard.py` | 200–329, 365–504, 628–737 |
| `tools/visual_guard/capture.py` | 1–140 (whole) |
| `tools/visual_guard/diff.py` | 1–125 (whole) |
| `tools/visual_guard/fixtures.py` | 1–339 (whole) |
| `.github/workflows/ci.yml` | 1–32 (whole) |
| `docs/screenshots/ui-v2-20261014/browser/{home-1100,fallback-no-blur}.png` | viewed |
| `ui/web_new_v2/assets/theme-previews/{01_Dark,05_Mint}.png` | viewed |
| `.venv_win/Lib/site-packages/webview/{__init__,http,util}.py` | pywebview serving model (local-URL → Bottle server, threaded adapter) |

**Callees traced into other areas**

- `ui/web_new_v2/js/appearance-assets.js` → `ui/web_new_v2/js/settings-view.js` → `ui/web_new_v2/js/settings.js` (theme preview / background resolution) — **JS side belongs to WN-30**; the CSS/asset contract consequences are reported here.
- `ui/web_new_v2/js/efficiency.js::initBlurObserver` (WN-31) — the `.blur-out` IntersectionObserver that is supposed to mitigate the `backdrop-filter` cost.
- `core/ui_assets.py::install_macos_assets` (WN-16) — the only mechanism that makes `ui/MACos_ui/**` reachable from the page.
- `main.py` window/bootstrap (WN-01) — the `Cache-Control: no-cache` hook and the `file://`→HTTP serving model.
- `setup_pyinstaller.spec` / `installer.iss` (WN-01) — what actually ships.

**Machine-measured inventory (all reproduced by the scripts described in the findings)**

| Metric | Value |
|---|---|
| CSS linked from `index.html` | **25 files, 426,845 B (416.8 KB)** |
| `base.css` | 129,322 B (30.3 %), 4,633 lines, **695 distinct selectors** |
| Per-view CSS that could be deferred (12 view sheets + lyrics/home-view/track-table/player-view) | ≈ **161.7 KB (38.8 %)** of the CSS |
| `backdrop-filter` declarations in the linked set | 76 (48 active) — **41 active in the shared layer, on 27 real element selectors** |
| `filter: … blur(…)` declarations | 86 (74 shared) |
| `!important` in the linked set | **442** (250 in `base.css` alone) |
| Cross-file conflicting `(selector, property)` pairs (shared layer) | **200 across 69 selectors**; 99 selectors defined in >1 stylesheet |
| Custom properties declared in **both** `tokens.css` and `base.css` | **10, of which 9 disagree** |
| Raw colour literals in the component/MACos layer | ~900 (119 hex + 271 `rgb()` in `base.css` alone); 36 white `color:` declarations with **no** `var()` at all, 91 white backgrounds |
| Assets shipped | 9,736,340 B in `web_new_v2/assets` + 1,425,866 B in `MACos_ui/assets` = **10.64 MB** |
| Dead assets | **634,701 B (620 KB)** |
| `tools/visual_guard/goldens/` | **0 PNG files** |

---

### 2. Findings

#### F-WN-33-1  [P1] — `home-refresh.css` re-declares the `dark` theme palette, so the shipped Dark preset is green, not the purple `themes.css` defines

- **File:** `ui/web_new_v2/css/components/home-refresh.css:12-24` (the override), `ui/web_new_v2/index.html:28` (themes.css) and `:35` (home-refresh.css), `ui/web_new_v2/css/themes.css:68-83` (the real Dark palette)
- **Confirmed:** yes
- **Description:** `themes.css` owns the raw palette and declares Dark as `#0a0a0f` / `#a855f7` (purple). `home-refresh.css` — a *view* stylesheet, loaded **after** `themes.css` — re-declares **11** palette tokens for the very same selector `:root[data-theme="dark"]`: `--bg-main`, `--bg-surface`, `--bg-card`, `--primary`, `--primary-rgb`, `--primary-fg`, `--accent`, `--accent-glow`, `--ambient-glow`, `--text-sec`, `--text-dim`. The values are a completely different green palette (`#061711` / `#18d6a2`). Both rules have identical specificity `(0,2,0)`; the later `<link>` wins. The Dark preset in `themes.css` is therefore dead code, and the app's default theme is not the one the theme system declares.
- **Cause:** a per-view stylesheet was allowed to own raw palette tokens. The `tokens.css` header states the contract ("this file owns the SEMANTIC layer, themes.css owns the RAW PALETTE", `tokens.css:10-15`) but nothing enforces it — the rule "only `themes.css` may declare a palette token" is prose, not a check.
- **Trigger conditions:** any launch with `data-theme="dark"` — i.e. the default (`index.html:2` `data-theme="dark"`) and the `dark` entry of the 22-preset picker (`js/settings.js:493`).
- **User impact:** the Dark preset shows a dark green/teal app instead of the documented violet; every theme edit made in `themes.css` (including the 13 measured WCAG ratios in the Light-theme block) has no effect on the default theme; the "Current" style preview swatch in the picker is hard-coded green (`css/components/ui-style-picker.css:17` `.preview-current { background: #10251f; }`) and agrees with the override rather than with `themes.css`.
- **Evidence:**
  ```css
  /* ui/web_new_v2/css/components/home-refresh.css:12-24 */
  :root[data-theme="dark"] {
      --bg-main: #061711;
      --bg-surface: #0c241c;
      --bg-card: #12382d;
      --primary: #18d6a2;
      --primary-rgb: 24, 214, 162;
      --primary-fg: #04261c;
      --accent: #18d6a2;
      ...
  }
  ```
  ```html
  <!-- ui/web_new_v2/index.html:28 and :35 -->
  <link rel="stylesheet" href="css/themes.css?v=20260827_blur">
  ...
  <link rel="stylesheet" href="css/components/home-refresh.css?v=20261014_home">
  ```
  Only two files in the whole linked set declare `[data-theme="dark"]` (grep of `ui/` → `themes.css:68`, `home-refresh.css:12`); nothing after `home-refresh.css` re-declares it (`MACos_ui/*` is scoped to `[data-ui-style="macos"]`).
- **Reproduction / verification:** open the app, press F12 in the WebView2 devtools and run
  `getComputedStyle(document.documentElement).getPropertyValue('--primary')` → `24, 214, 162` (expected by `themes.css`: `168, 85, 247`).
  Static: `grep -n 'data-theme="dark"\]' ui/web_new_v2/css/**/*.css` returns exactly `themes.css:68` and `home-refresh.css:12`; `index.html:35 > index.html:28`.
  The same discrepancy is baked into the visual-guard fixture, which seeds `accent_color="#a855f7"` for the `dark` theme (`tools/visual_guard/fixtures.py:316`) — i.e. the harness itself expects the purple that the app no longer renders.
- **Suggested fix:** move the `home-refresh.css` `:root[data-theme="dark"]` block into `themes.css` (as a distinct preset, e.g. `data-theme="cyber-blossom"`), or delete it and re-point `--home-*` at the existing tokens. Add a static check that a palette token (`--primary`, `--bg-main`, `--accent`, `--text-*`, `--border*`, `--success/--error/--warning`) is only ever declared in `themes.css` (plus the `:root[data-ui-style="macos"]` override).
- **Fix side effects:** the app's default accent changes from green back to purple — a visible product change that must be re-reviewed against the reference screenshots in `docs/screenshots/ui-v2-20261014/` (which are purple).
- **Discovered by:** B

---

#### F-WN-33-2  [P1] — The 22 theme presets download 4.8 MiB of 1600-px wallpapers to paint 186×58 boxes, while the purpose-built 306 KB thumbnails sit unused

- **File:** `ui/web_new_v2/js/appearance-assets.js:29,48`, `ui/web_new_v2/js/settings-view.js:12-14`, `ui/web_new_v2/js/settings.js:579` and `:108`
- **Confirmed:** yes for the dead thumbnails and for the byte counts; the exact moment the browser issues the fetches is a hypothesis (see below)
- **Description:** `themePreviewPath(id)` in `appearance-assets.js` returns `assets/backgrounds/photo-<id>.jpg` — a **1600 px-wide wallpaper** (154 KB – 471 KB each). `settings-view.js:13` uses it as the *primary* source and only falls back to `assets/theme-previews/<name>.png` (the real 185×58 crops) if it returns an empty string, which it never does for the 22 preset ids. The preset grid renders 22 `<img src=… width="186" height="58" loading="lazy">` (`js/settings.js:579`) and `initSettingsView` inserts **22 more** identical 160-px preview `<img>`s for the "Встроенные фоны" gallery (`js/settings.js:108` → `js/settings-view.js:100`). `initSettings()` runs at boot (`js/main.js:536` → `js/settings.js:104 renderThemeGrid()`), so all 44 `<img>` elements exist in the DOM from first paint. The 17 shipped PNGs (313,370 B) are never requested.
- **Cause:** the artwork catalogue was repurposed as the theme-thumbnail source without re-rendering the thumbnails. The PNG crops that were built for exactly this slot (185×58 — matching the HTML's `width`/`height` attributes) were left in place and orphaned.
- **Trigger conditions:** every app start (the elements are created) and every time the Settings view is opened.
- **User impact:** ~4.8 MiB of distinct JPEG transferred (5,026,343 B over 17 distinct files) and **decoded** to render 44 boxes of 186×58 CSS px. Each 1600×1067 JPEG decodes to a ~6.8 MB RGBA bitmap; the 1600×2400 portrait ones to ~15.4 MB. The 306 KB of purpose-built thumbnails that would have cost 1/17th of the bytes sit on disk unused.
- **Evidence:**
  ```js
  // ui/web_new_v2/js/appearance-assets.js:29,48
  const localPath = id => `assets/backgrounds/${id}.jpg`;
  ...
  themePreviewPath: id => themes[id] ? localPath(`photo-${themes[id]}`) : '',
  ```
  ```js
  // ui/web_new_v2/js/settings-view.js:12-14
  export function themePreviewPath(id) {
      return window.NeDotifyAssets?.themePreviewPath(id) || (THEME_IMAGES[id] ? `assets/theme-previews/${THEME_IMAGES[id]}.png` : '');
  }
  ```
  ```html
  <!-- ui/web_new_v2/js/settings.js:579 -->
  <span class="theme-preview"><img src="${themePreviewPath(t.id)}" class="theme-preview-image" alt="" width="186" height="58" loading="lazy"></span>
  ```
  Asset inventory: `assets/theme-previews/*.png` = 17 files, 313,370 B, all exactly 185–188 × 55–58 px. The 17 distinct JPEGs referenced by the theme map = 5,026,343 B.
- **Reproduction / verification:**
  1. Dead-asset proof: `grep -rn "theme-previews" ui/ --include=*.js --include=*.html --include=*.css` → only `js/settings-view.js:13` (the unreachable `||` branch) and `docs/UI_V2_SETTINGS.md:5`.
  2. Byte proof: `appearance-assets.js` `themes` map has 22 entries → 17 distinct `photo-*.jpg`; summing their sizes gives 5,026,343 B.
  3. Runtime proof (hypothesis → measurement): open the app, DevTools → Network → filter `Img`, open Settings → Appearance; observe whether the 1600-px JPEGs are transferred. **Evidence still missing:** the `loading="lazy"` deferral is not guaranteed to suppress them, because the settings overlay is `visibility: hidden; opacity: 0` but `display: flex !important` (`css/components/base.css:3045-3062`) — a laid-out, geometrically-on-screen box, which Chromium's lazy-load heuristic *may* still treat as in-viewport. I could not run the WebView2 app in this environment, so the *fetch timing* is a hypothesis; the *dead thumbnails* and the *byte counts* are confirmed.
- **Suggested fix:** make `themePreviewPath()` return the 185×58 PNG (or a new 200-px-wide WebP derivative of the wallpaper) and keep the wallpaper only for the "apply as background" action. Do not reference the full-size JPEG from an `<img>` that is 186 px wide.
- **Fix side effects:** the previews change from "a photo of a forest" to the 185×58 crop the user already designed; the `docs/UI_V2_SETTINGS.md:5` description matches the PNG behaviour, so the code is the part that drifted.
- **Discovered by:** B

---

#### F-WN-33-3  [P2] — 8.64 MB of wallpapers and 1.36 MB of PNG backdrop are shipped in the installer; every one is 1600 px wide and CSS-scaled with `cover`

- **File:** `setup_pyinstaller.spec:27`, `ui/web_new_v2/assets/backgrounds/*.jpg` (27 files), `ui/MACos_ui/assets/atmosphere-dusk.png`
- **Confirmed:** yes
- **Description:** `extra_datas = [('ui/web_new_v2', 'ui/web_new_v2'), ('ui/MACos_ui', 'ui/MACos_ui')]` bundles the *entire* UI tree into the PyInstaller executable, which `installer.iss:44` then ships as `NeDotify_Setup.exe`. That includes 8,850,989 B of wallpapers and a 1,424,752 B PNG. All 27 JPEGs are 1600 px on the long edge; four are 1600×2400 portraits. The macOS backdrop is a 1727×910 PNG used at `background-size: cover` (`ui/MACos_ui/interface.css:11`) with an additional `filter: saturate(.75) blur(var(--mac-wallpaper-blur,0px))` applied to the whole viewport.
- **Cause:** no size budget, no derivative generation, no format negotiation. Wallpapers are served as 1600-px originals to a desktop window whose content area is ~1100×800 (min 600×640).
- **Trigger conditions:** installing the app (10.64 MB of payload for imagery) and painting a background.
- **User impact:** (a) the installer is ~10 MB larger than it needs to be; (b) each background costs 6.8–15.4 MB of decoded RGBA in the compositor; (c) the macOS backdrop is a 1.36 MB PNG decoded to 6.3 MB and then blurred per frame.
- **Evidence:**
  ```python
  # setup_pyinstaller.spec:27
  extra_datas = [('ui/web_new_v2', 'ui/web_new_v2'), ('ui/MACos_ui', 'ui/MACos_ui')] + collect_data_files('ytmusicapi')
  ```
  ```css
  /* ui/MACos_ui/interface.css:11 */
  html[data-ui-style="macos"] #macos-backdrop { ... background-image: linear-gradient(#0a0f141a,#0a0f141a),url("assets/atmosphere-dusk.png"); background-size: cover; ... filter: saturate(.75) blur(var(--mac-wallpaper-blur,0px)); }
  ```
  Measured: `assets/backgrounds` = 27 files / 8,850,989 B; largest `photo-1503899036084-c55cdd92da26.jpg` = 1,307,705 B at 1600×2400; `MACos_ui/assets/atmosphere-dusk.png` = 1,424,752 B at 1727×910.
- **Reproduction / verification:** `Get-ChildItem ui/web_new_v2/assets/backgrounds | Measure-Object Length -Sum` → 8,850,989; `System.Drawing.Image::FromFile(...)` for each file to read the dimensions; `setup_pyinstaller.spec:27` for the bundling rule.
- **Suggested fix:** ship 1920-px-wide (or 2560-px for 4K) WebP/AVIF derivatives at quality ~72 (a 1600×1067 JPEG at q72 is ~120 KB → ~60 KB as WebP) and generate the macOS backdrop as a WebP; move the full-resolution originals out of the installer.
- **Fix side effects:** the wallpaper set becomes lossy; a visual-regression pass over the wallpaper catalogue is needed (the visual guard has no goldens — see F-WN-33-9).
- **Discovered by:** B

---

#### F-WN-33-4  [P2] — 416.8 KB of CSS across 25 render-blocking `<link>` tags, re-fetched and re-parsed on every cold start

- **File:** `ui/web_new_v2/index.html:17-50`, `main.py:69-73`
- **Confirmed:** yes
- **Description:** 25 `<link rel="stylesheet">` elements sit in `<head>`, all render-blocking, totalling 426,845 B. `base.css` alone is 129,322 B / 4,633 lines / 695 selectors. The app is served by pywebview's Bottle server over `http://127.0.0.1:<port>` (the window URL is a local filesystem path, `main.py:350` → `webview/http.py:98-104` roots the server at `ui/web_new_v2`), and **both** pywebview (`webview/http.py:127-129`) and the app's own `after_request` hook (`main.py:69-73`) stamp `Cache-Control: no-cache, no-store, must-revalidate, max-age=0` on every response. Nothing is cached between runs, so each cold start re-transfers and re-parses the full 416.8 KB and re-fetches the fonts.
- **Cause:** the split into 25 files was done for *authoring* reasons, but the loading strategy was never changed to match — there is no bundling, no `media` trick, no `rel="preload"`, and no per-view deferral.
- **Trigger conditions:** every application start. The measured cold start to "window loaded" in the repo's own bench is **2,156 ms** (`tools/bench/results/optimization-before-20261015-154303.json`, `cold_start.to_window_loaded_ms: 2156.3`), of which the CSS is a blocking serial dependency.
- **User impact:** ~161.7 KB (38.8 %) of the CSS belongs to views that are not on screen at start (lyrics, home, track-table, player-view, search, library, downloads, smart-playlists, feature-tools, settings, onboarding, profile). It is downloaded, parsed and style-recalculated before the first paint, for nothing.
- **Evidence:**
  ```html
  <!-- ui/web_new_v2/index.html:17-50 (25 links) -->
  <link rel="stylesheet" href="css/fonts.css?v=20261006_fonts">
  <link rel="stylesheet" href="css/tokens.css?v=20260827_blur">
  <link rel="stylesheet" href="css/components/base.css?v=20261012_catalog_lyrics">
  ...
  <link rel="stylesheet" href="MACos_ui/library.css?v=20261017_library">
  ```
  ```python
  # main.py:69-73
  @app.hook('after_request')
  def _disable_http_cache():
      _bottle.response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
  ```
- **Reproduction / verification:** sum the `Length` of the 25 hrefs → 426,845 B; count the `<link rel="stylesheet">` in `index.html` → 25; `main.py:71` for the no-cache header; `webview/http.py:127` for pywebview's own copy of the same header. Cold-start number: `tools/bench/results/optimization-before-20261015-154303.json` → `aggregate.medians["cold_start.to_window_loaded_ms"] = 2156.3`.
- **Suggested fix:** keep `fonts.css`, `tokens.css`, `base.css` and `themes.css` blocking; load the per-view sheets on first navigation of that view (`<link rel="stylesheet" media="print" onload="this.media='all'">` or a small `ensureStyles()` helper), or concatenate the blocking set into one file to remove 24 round trips.
- **Fix side effects:** per-view sheets loaded on demand cause a one-frame flash of unstyled content on first navigation of each view unless the preload happens on `pointerdown`/`mouseenter`; the `no-cache` header also means the deferral benefit is only paid once per view per session.
- **Discovered by:** B

---

#### F-WN-33-5  [P2] — 27 always-on `backdrop-filter` surfaces in the shared layer, including three viewport-sized ones and a full-screen 40 px blur; the mitigation only covers 4 of them

- **File:** `ui/web_new_v2/css/components/base.css:589,828,3685,2587,3050,3076,3730,4268,4428,3924,907,997,1115`, `css/components/visual-polish.css:77`, `css/components/player-bar.css:50,452`, `css/components/lyrics.css:245`, `css/components/home-refresh.css:171-175`, `ui/web_new_v2/js/efficiency.js:11`
- **Confirmed:** yes for the inventory; the resulting frame-rate impact is a hypothesis (see "Reproduction")
- **Description:** the linked stylesheets declare **41 active** `backdrop-filter` declarations in the shared layer (55 total, 14 of them `none`) on **27 distinct element selectors** plus 3 `html.has-custom-bg` variants and 2 `@supports` wrappers. The permanently-painted ones include:
  - `#sidebar` (`base.css:589`, overridden to `blur(var(--glass-blur)) saturate(150%)` by `home-refresh.css:172`) — a 226-px-wide, full-height column;
  - `#main-content` (`base.css:828` → `home-refresh.css:173`) — the whole content area;
  - `#player-bar` (`player-bar.css:50` → `visual-polish.css:77`) — full width;
  - `#lyrics-overlay` — `backdrop-filter: blur(40px)` (`lyrics.css:245`) over the entire viewport;
  - `#queue-drawer` — `blur(28px) saturate(160%)` (`player-bar.css:452`);
  - `.settings-modal-card` — `blur(32px) saturate(150%)` (`base.css:3076`);
  - `#mini-player-overlay` — `blur(24px) !important` (`base.css:2587`);
  - `#batch-action-bar` — `blur(24px)` (`base.css:4428`); `#custom-context-menu` — `blur(20px)`; `.search-suggestions-dropdown` — `blur(20px)`; `.custom-glass-dropdown-menu` — `blur(16px)`; `.search-platform-dropdown` — `blur(var(--blur-xl))`; `.search-capsule`, `.card`, `.glass-panel`, `.toast`, `.context-menu`, `.modal-content`, `.top-bar`, `.network-banner`, `.pl-drag-ghost`, `.workshop-card-badge`, `.workshop-card-overlay`, `#mini-lyrics-widget`, `.player-glass-card`.
  The `blur-out` IntersectionObserver (`js/efficiency.js:11`) only watches **`.card, .glass-panel, .player-glass-card, .settings-modal-card`** — it can never switch off `#sidebar`, `#main-content`, `#player-bar`, `#lyrics-overlay`, `#queue-drawer` or any of the dropdowns.
- **Cause:** the glass effect was applied per-component as it was written, with no central inventory of "how many backdrop-filtered surfaces are simultaneously live", and the IntersectionObserver mitigation was scoped to the four classes that happened to exist when it was written.
- **Trigger conditions:** always. The three viewport-sized surfaces are behind an animated particle canvas (`#particles-bg`, `js/particles.js:301-317`, 24–30 FPS), so the backdrop snapshot has to be re-blurred on essentially every frame.
- **User impact:** on a low-end GPU, three large blur surfaces + a full-screen 40 px overlay + a per-frame canvas blur is the classic recipe for a 60 fps → 30 fps collapse. The `docs/screenshots/…/fallback-no-blur.png` reference in the brief is the visual proof that the maintainers already know the no-blur path is a supported state.
- **Evidence:**
  ```css
  /* ui/web_new_v2/css/components/lyrics.css:245-246 */
  backdrop-filter: blur(40px);
  -webkit-backdrop-filter: blur(40px);
  ```
  ```css
  /* ui/web_new_v2/css/components/base.css:3685-3686 */
  backdrop-filter: blur(var(--glass-blur)) saturate(180%);
  -webkit-backdrop-filter: blur(var(--glass-blur)) saturate(180%);
  /* selector: #sidebar, #player-bar, .top-bar, .context-menu, .modal-content, .glass-panel */
  ```
  ```js
  // ui/web_new_v2/js/efficiency.js:11
  const selector = '.card, .glass-panel, .player-glass-card, .settings-modal-card';
  ```
  Counts: 76 `backdrop-filter` declarations in the linked set (48 active); 86 `filter: … blur(…)` declarations.
- **Reproduction / verification:**
  1. Static: the inventory above is reproducible with a regex sweep over the 25 linked stylesheets (I used `(?<!-)\bbackdrop-filter\s*:`); it yields 55 shared / 21 macOS declarations.
  2. Runtime (hypothesis → what would confirm it): the `tools/bench/results/` folder already contains a `cpu_attribution` scenario; run `python tools/bench/run_bench.py --scenario cpu_attribution --tracks 2000 --seconds 8` with the perf preset on `high` vs `low` (`base.css:159-180` sets `--blur-*` to 0 in `:root.perf-low`) and compare the renderer CPU. **Evidence still missing:** I did not run the app or the bench in this environment (it launches a GUI WebView2), so the frame-rate delta is not measured here.
- **Suggested fix:** (a) extend the `blur-out` observer to the viewport-sized surfaces (`#sidebar`, `#main-content`, `#player-bar`) and to the overlay surfaces; (b) make the `blur-*` radii user-visible in the Optimisation panel (they already are: `js/settings.js` writes `--glass-blur`); (c) replace the always-on `#lyrics-overlay` 40 px blur with a scrim + a blur only on the text column.
- **Fix side effects:** the glass look changes; the `perf-low` preset already demonstrates the flat look is acceptable (`base.css:171-180`).
- **Discovered by:** B

---

#### F-WN-33-6  [P2] — A full-viewport `filter: blur(8px)` sits on the animated particle canvas: an 8.3 Mpx Gaussian blur re-applied every frame

- **File:** `ui/web_new_v2/css/components/base.css:1729-1730`, `ui/web_new_v2/js/particles.js:301-317`, `ui/web_new_v2/css/components/player-view.css:44`, `ui/web_new_v2/css/components/base.css:1579`
- **Confirmed:** yes
- **Description:** `#particles-bg` is a `position: fixed; inset: 0` container (index.html:76) into which `particles.js` appends a full-viewport `<canvas>` sized `innerWidth × innerHeight × devicePixelRatio` and repaints at up to 24–30 FPS (`index.html:1640`, default 24). `base.css:1729` applies `filter: blur(8px)` to `#particles-bg` — i.e. the *whole canvas* is blurred every time the canvas changes. The same sheet also applies `filter: blur(25px) brightness(0.35) saturate(1.4)` to `.rich-menu-header-bg` (a full-width menu header) and `player-view.css:44` applies `filter: blur(var(--ambient-blur))` (= 50 px) to `.player-bg-glow`.
- **Cause:** the blur was written as a cheap "soften the particles" effect; a `filter` on a container is not a one-off — it is re-evaluated whenever the filtered content changes, which for an animating canvas is every frame.
- **Trigger conditions:** particles enabled (the default) — i.e. the app is permanently in this state.
- **User impact:** at 1920×1080 @ DPR 2 the canvas is 3840×2160 = 8.3 Mpx; an 8 px separable Gaussian over 8.3 Mpx per frame is a large, sustained GPU cost that runs *underneath* three backdrop-filtered surfaces, each of which then has to re-blur the result.
- **Evidence:**
  ```css
  /* ui/web_new_v2/css/components/base.css:1729-1730 */
  filter: blur(8px);
  -webkit-filter: blur(8px);
  /* selector: #particles-bg */
  ```
  ```js
  // ui/web_new_v2/js/particles.js:301-317
  canvas = document.createElement('canvas');
  canvas.id = 'particles-canvas';
  canvas.style.cssText = 'position:absolute;top:0;left:0;width:100%;height:100%;...';
  container.appendChild(canvas);
  ...
  sizeCanvasForDpr(canvas, ctx, newW, newH);
  ```
  ```css
  /* ui/web_new_v2/css/components/player-view.css:44 */
  filter: blur(var(--ambient-blur));   /* --ambient-blur: 50px  (tokens.css:95) */
  ```
- **Reproduction / verification:** open the app with particles on, open the WebView2 devtools → Rendering → *Paint flashing* / *Frame rendering stats*, or simply compare the renderer process CPU with particles on vs off (`js/settings.js:657-665` toggles `particles_enabled`). Static confirmation of the filter/canvas pairing: `base.css:1729` + `index.html:76` + `particles.js:295-305`.
- **Suggested fix:** draw the soft look inside the canvas (the particle sprites are already pre-rendered offscreen — `particles.js:95-234` — so a blurred sprite variant costs nothing extra) and delete the CSS `filter`; keep a static (non-animated) blurred copy for the reduced-motion path.
- **Fix side effects:** particle edges will look slightly different; the sprite atlas has to be regenerated.
- **Discovered by:** B

---

#### F-WN-33-7  [P1] — Two style systems layered on top of each other: 200 cross-file conflicting `(selector, property)` pairs on 69 selectors; "I changed it and nothing happened" is the expected outcome

- **File:** `ui/web_new_v2/css/components/base.css` (695 selectors) vs `components/visual-polish.css:61,77,118`, `components/track-table.css`, `components/home-refresh.css:3-11,148`, `components/settings-refresh.css:2-5`, `components/player-bar.css:50`, `components/search-refresh.css`, `components/library-refresh.css`
- **Confirmed:** yes
- **Description:** the 12 `*-refresh.css` sheets are a *second* style system layered over `base.css`, not a refinement of it. Measured over the 21 shared (non-macOS) stylesheets: **99 selectors are declared in more than one file**, and **200 `(selector, property)` pairs are declared with conflicting values in different files**, spread over 69 selectors. Breakdown by file pair: base↔visual-polish 34, base↔track-table 25, base↔home-refresh 20, base↔settings-refresh 17, home-refresh↔player-bar 11, base↔search-refresh 11, home-refresh↔library-refresh 11, onboarding↔settings-refresh 9, home-refresh↔themes 8.
- **Cause:** `base.css` was never reduced when the `*-refresh.css` sheets were added; both keep full declarations for the same elements and the winner is decided by `<link>` order.
- **Trigger conditions:** any edit to a `base.css` rule that a `*-refresh.css` also declares.
- **User impact:** edits silently do nothing, and the override is invisible in the source. Concrete examples:
  - `--player-bar-height`: `player-bar.css` = `84px`, `home-refresh.css:9` = `92px` → the player bar is 92 px tall, the 84 px value is dead; `--player-bar-offset` `20px` vs `16px`; at `max-width: 600px` `72px` vs `70px`.
  - `#player-bar` `backdrop-filter` is declared **three times with three different values** (`base.css:3685` `blur(var(--glass-blur)) saturate(180%)`, `player-bar.css:50` `blur(16px)`, `visual-polish.css:77` `blur(var(--glass-blur,16px)) saturate(160%)`).
  - `.search-capsule` `backdrop-filter`: `base.css:997` `blur(var(--blur-sm))` vs `visual-polish.css:61` `blur(var(--blur-md)) saturate(160%)`.
  - `#sidebar` `align-items`: `base.css` `center` vs `home-refresh.css:35` `stretch`; `#view-settings…align-items`: `base.css` `center` vs `settings-refresh.css:2` `stretch`.
  - `#main-content` / `#sidebar` / `#player-bar` `background`: declared 2–3 times each with different `color-mix()` expressions, the last one winning.
  - `!important` is used **442** times in the linked set (250 in `base.css` alone) as the tie-breaker.
- **Evidence:**
  ```css
  /* ui/web_new_v2/css/components/player-bar.css — :root */
  --player-bar-height: 84px;
  /* ui/web_new_v2/css/components/home-refresh.css:9 — :root */
  --player-bar-height: 92px;
  ```
  ```css
  /* ui/web_new_v2/css/components/base.css:3685 */
  backdrop-filter: blur(var(--glass-blur)) saturate(180%);
  /* ui/web_new_v2/css/components/player-bar.css:50 */
  backdrop-filter: blur(16px);
  /* ui/web_new_v2/css/components/visual-polish.css:77 */
  backdrop-filter: blur(var(--glass-blur, 16px)) saturate(160%);
  ```
- **Reproduction / verification:** parse the 21 shared stylesheets into `(selector → [(file, property, value)])` and report every property that appears with ≥2 distinct values across ≥2 files — 200 pairs / 69 selectors. The three `--player-bar-height` declarations are visible with `grep -n "player-bar-height" ui/web_new_v2/css/`.
- **Suggested fix:** treat `base.css` as the single owner of the base rules: for each of the 69 conflicting selectors, delete the losing declaration from the `*-refresh.css` sheet and keep only the *new* properties the refresh layer introduces. Add the conflict detector as a test (it is ~40 lines) so the count can only go down.
- **Fix side effects:** deleting the losing declarations changes the rendered result wherever the winner was not the intended one — that is the point, but it needs a visual pass, and the visual guard has no goldens (F-WN-33-9), so the pass has to be manual.
- **Discovered by:** B

---

#### F-WN-33-8  [P2] — `tokens.css` claims every token is "declared EXACTLY ONCE"; 10 are declared twice and 9 disagree

- **File:** `ui/web_new_v2/css/tokens.css:8-31` (the claim) and `:87-95`; `ui/web_new_v2/css/components/base.css:113-125`
- **Confirmed:** yes
- **Description:** `tokens.css:17-19` states: *"every name below is declared EXACTLY ONCE in the whole stylesheet set. The two files used to re-declare 22 of these names, so which value won depended on which `<link>` came last … Because var() is resolved after the cascade, the order is now irrelevant"*. That is false. `base.css` re-declares **10** of `tokens.css`'s custom properties in its own `:root` block: `--glass-blur`, `--blur-sm`, `--blur-md`, `--blur-lg`, `--blur-xl`, `--player-glow-blur`, `--player-glow-opacity`, `--ambient-blur`, `--app-bg-opacity`, `--font-family`. **9 of the 10 disagree**; only `--app-bg-opacity` matches. `base.css` is linked *after* `tokens.css` (`index.html:21` vs `:22`), so **`tokens.css`'s values are dead** — e.g. `--player-glow-opacity: 0.55` in `tokens.css:93` is overridden by `0.5` in `base.css:124`, and `--font-family: var(--font-body)` in `tokens.css:102` is overridden by the `var(--font-body, 'DM Sans', …)` form in `base.css:32`.
- **Cause:** the ownership rule was written down but never enforced; the two files were not reconciled when `base.css` gained a performance-preset block.
- **Trigger conditions:** always.
- **User impact:** a token edit in `tokens.css` has no effect, silently. The "order is now irrelevant" property the file claims as its core invariant does not hold — the whole point of the semantic/raw split (so a theme can set `--accent` and have `--primary` follow) is undermined because the blur/typography layer is still order-dependent.
- **Evidence:**
  ```css
  /* ui/web_new_v2/css/tokens.css:87-95 */
  --glass-blur: 8px;
  --blur-sm: calc(var(--glass-blur) * 0.75);
  ...
  --player-glow-opacity: 0.55;
  ```
  ```css
  /* ui/web_new_v2/css/components/base.css:115-124 */
  --glass-blur: 8px;
  --blur-sm:    calc(var(--glass-blur) * 0.75);
  ...
  --player-glow-opacity: 0.5; /* Ambient glow opacity */
  ```
  ```css
  /* ui/web_new_v2/css/tokens.css:17-19 */
  every name below is declared EXACTLY ONCE in the whole stylesheet set. The two files used to re-declare 22 of these names, so which value won depended on which <link> came last in index.html - correctness was an accident of the link order.
  ```
- **Reproduction / verification:** collect all `--name:` declarations in `tokens.css` and in `base.css` and intersect: 10 names, 9 with differing value sets (the difference is the perf-preset overrides in `base.css:159-180`, which are legitimate — but the *base* value in `base.css` still shadows `tokens.css`).
- **Suggested fix:** delete the duplicated block from `base.css:113-125` (keep only the perf-preset overrides in `:root.perf-medium` / `:root.perf-low`, which have their own specificity) and leave `tokens.css` as the single owner; add a test that asserts each custom property is declared in exactly one file (per scope).
- **Fix side effects:** `--player-glow-opacity` becomes 0.55 instead of 0.5 → the ambient album-art glow gets ~10 % brighter; `--font-family` loses its `'Segoe UI'` fallback chain tail in `base.css` but keeps it via `--font-body` in `tokens.css:101`.
- **Discovered by:** B

---

#### F-WN-33-9  [P2] — The visual guard's pixel half is a vacuous pass (zero goldens) and its CSS half is currently RED; neither runs in CI

- **File:** `tools/visual_guard/goldens/` (empty directory), `tools/visual_guard/diff.py:113-124`, `tools/visual_guard/run_guard.py:502-620` and `:688-722`, `tools/bench/results/animation_declarations.json`, `.github/workflows/ci.yml:28-30`, `tests/test_visual_guard_diff.py:121-133`
- **Confirmed:** yes
- **Description:** the harness has two halves. The **pixel** half compares `tools/visual_guard/goldens/` against a fresh capture. `goldens/` contains **0 PNG files**; `fixtures.py` defines 8 screens × 3 themes × 2 viewports × 2 DPRs = 96 captures that were never taken. `diff.py:113-124` computes `"ok": not failures and not missing` — with an empty goldens directory, `failures == []` and `missing == []`, so the pixel half returns **`ok: true` with `compared: 0`**. It is a vacuous pass, exactly the failure mode `tests/test_visual_guard_css_decls.py:16-19` describes for the CSS half ("measured on a clean tree, baseline 296 / current 745 / intersection 0 / ok is True"). The **CSS** half, run against the real tree, is currently **failing**: `css_declaration_guard()` returns `ok=False`, `baseline_declarations=651`, `current_declarations=438`, `removed=302`, `added=89`, `changed=2`, `intersection_keys=67`. And nothing runs it: CI executes only `pytest -m "not network"`, and the pytest files exercise the guard exclusively against synthetic trees in `tmp_path` — there is **no** test that asserts the real tree's guard state.
- **Cause:** the capture step needs a GUI WebView2 + CDP session (`capture.py:1-17`, `--port 9222`), which cannot run on `windows-latest` CI, and no one re-recorded the goldens locally after the CSS churn.
- **Trigger conditions:** always.
- **User impact:** the app has **no working visual-regression gate**. The specific regressions this audit found — the Dark-theme palette override (F-WN-33-1) and the 200 conflicting declarations (F-WN-33-7) — are exactly the class of change the pixel half exists to catch, and it would have caught the first one (the fixture seeds `accent_color="#a855f7"`, `fixtures.py:316`).
- **Evidence:**
  ```python
  # tools/visual_guard/diff.py:113-124
  failures = [r for r in results if not r["ok"]]
  return {
      "ok": not failures and not missing,
      ...
      "compared": len(results),
  ```
  ```yaml
  # .github/workflows/ci.yml:28-30
  - name: Run Python tests
    run: |
      pytest -m "not network"
  ```
  Measured on the real tree: `tools.visual_guard.run_guard.css_declaration_guard()` → `{"ok": false, "baseline_declarations": 651, "current_declarations": 438, "removed": 302, "added": 89, "changed": 2, "intersection_keys": 67, "vacuous": false}`; `tools.visual_guard.diff.compare_sets(goldens, goldens)` → `{"ok": true, "compared": 0, "passed": 0, "failed": 0, "missing": []}`.
- **Reproduction / verification:** `Get-ChildItem tools/visual_guard/goldens` → 0 files; the two Python one-liners above; `pytest -m "not network"` never touches `css_declaration_guard()` on the real tree (grep `css_declaration_guard` in `tests/` → only `tests/test_visual_guard_css_decls.py`, always with `root=tmp_path`).
- **Suggested fix:** (a) make `compare_sets` fail when `compared == 0` and `goldens` is empty (a "no goldens" state must not be a pass); (b) add a pytest that runs `css_declaration_guard()` against the repo root and fails when `ok` is false, so the 302 removed declarations cannot rot silently; (c) record the 96 goldens on a developer machine and commit them.
- **Fix side effects:** (a) and (b) will turn the build red until the baseline is re-recorded (`--write-css-baseline`) — which is the intended behaviour but must be scheduled.
- **Discovered by:** B

---

#### F-WN-33-10  [P2] — The CSS declaration guard cannot see the defects it exists to catch: it is keyed on (file, property) and never looks at selectors, themes or cross-file overrides

- **File:** `tools/visual_guard/run_guard.py:369-398` (`collect_declarations`), `:214-218` (`WATCHED_VALUE_TOKENS`, `WATCHED_VARS`)
- **Confirmed:** yes
- **Description:** the guard buckets declarations by `f"{rel}|{decl['property']}"` — the **selector is discarded**. Consequences: (a) moving a `backdrop-filter` from `.foo` to `.bar` inside the same file is invisible; (b) a rule that is *overridden* by a later stylesheet is invisible — the base.css value is recorded as still present; (c) the watched token list covers `transition`, `animation`, `backdrop-filter`, `filter:`, `will-change`, `contain:` plus a set of custom-property *prefixes* (`--blur-`, `--glass-blur`, `--app-bg-opacity`, `--player-glow-`, `--glow`, `--transition`, `--anim`, `--ease`, `--dur`, `--duration`) — it does **not** watch `--primary`, `--bg-main`, `--accent`, `--text-main`, `background`, `color` or `box-shadow`. The Dark-theme palette override (F-WN-33-1) is therefore doubly invisible: the token is not watched, and the override is not in a watched property.
- **Cause:** the guard was written to protect "what is painted" from silent removal, and the bucketing was optimised for line-number independence — but the bucketing key was chosen as (file, property) rather than (file, selector, property).
- **Trigger conditions:** always.
- **User impact:** the guard is green (or red for unrelated reasons) while the theme palette, the background colours and the box-shadows are being changed by a different file. It provides the *appearance* of a visual contract while covering only motion/blur declarations.
- **Evidence:**
  ```python
  # tools/visual_guard/run_guard.py:388-398
  for line in lines:
      low = line.lower()
      if not (any(t in low for t in WATCHED_VALUE_TOKENS)
              or any(v in low for v in WATCHED_VARS)):
          continue
      decl = extract_declaration(line)
      if not decl["property"]:
          continue
      key = f"{rel}|{decl['property']}"
      buckets.setdefault(key, []).append(decl["value"])
  ```
  ```python
  # tools/visual_guard/run_guard.py:214-218
  WATCHED_VALUE_TOKENS = ("transition", "animation", "backdrop-filter",
                          "filter:", "will-change", "contain:")
  WATCHED_VARS = ("--blur-", "--glass-blur", "--app-bg-opacity",
                  "--player-glow-", "--glow", "--transition", "--anim",
                  "--ease", "--dur", "--duration")
  ```
- **Reproduction / verification:** `grep -n 'WATCHED_VALUE_TOKENS\|WATCHED_VARS' tools/visual_guard/run_guard.py`; the `key` construction at line 396 shows the selector is not part of it. Then note that `home-refresh.css:12-24` declares `--primary`, `--bg-main`, `--accent` — none of which appear in `WATCHED_VARS`.
- **Suggested fix:** extend the key to `file|selector|property` (the baseline format already supports per-declaration records) and add the palette/background tokens to `WATCHED_VARS`; at minimum, add a dedicated test that asserts a palette token is only declared in `themes.css` (+ the macOS override scope) — that single test would have caught F-WN-33-1.
- **Fix side effects:** the baseline (`tools/bench/results/animation_declarations.json`, 190,702 B) has to be re-recorded; the guard becomes stricter and will surface more pre-existing conflicts at once.
- **Discovered by:** B

---

#### F-WN-33-11  [P2] — No Cyrillic webfont: DM Sans and Sora are `latin` + `latin-ext` only, so every Russian string in the UI falls back to Segoe UI

- **File:** `ui/web_new_v2/css/fonts.css:48-99` (all six `@font-face` rules), `ui/web_new_v2/index.html:2` (`<html lang="ru">`), `ui/web_new_v2/css/tokens.css:100-101`
- **Confirmed:** yes
- **Description:** the six bundled WOFF2 cuts are `dmsans-latin-{normal,italic}-400` and `dmsans-latin-ext-{normal,italic}-400` plus `sora-latin-600-normal` and `sora-latin-ext-600-normal` — 248,544 B total. Every `unicode-range` in `fonts.css` covers `U+0000-00FF` (Basic Latin) and `U+0100-02BA`/`U+1D00-1DBF`/… (Latin Extended); **none covers U+0400–U+04FF (Cyrillic)**. The document is `<html lang="ru">` and every user-visible string in `index.html` is Russian ("Главная", "Поиск", "Библиотека", "Настройки", "Профиль"). Because `unicode-range` restricts a face to its subset, every Cyrillic codepoint skips both DM Sans and Sora and falls through to the next family in the stack — `'Segoe UI'` / `system-ui` (`tokens.css:100-101`).
- **Cause:** the fonts were self-hosted from the Google Fonts CSS, which serves DM Sans and Sora with `latin` + `latin-ext` cuts only. The file's own header documents this as a deliberate decision ("KNOWN GAP — NOT AN OVERSIGHT", `fonts.css:26-34`), but the decision was taken without noticing that the *display* font (Sora, `--font-display`) therefore never paints a single heading in this app.
- **Trigger conditions:** always.
- **User impact:** every Russian heading, label and button is drawn in Segoe UI while Latin strings (artist/track/album names, the "NeDotify" wordmark) are drawn in Sora/DM Sans — two typefaces inside the same screen, and a visible FOUT/flash for the Latin faces while the Cyrillic text is already painted. The `font-weight: 750` used for headings (`home-refresh.css:54,84,127`) has no 750 cut in Segoe UI, so the weight is snapped to 700. The 248 KB of bundled fonts are therefore only ever used for Latin metadata.
- **Evidence:**
  ```css
  /* ui/web_new_v2/css/fonts.css:56-58 */
  @font-face {
      font-family: 'DM Sans';
      font-style: normal;
      font-weight: 400 700;
      font-display: swap;
      src: url('../assets/fonts/dmsans-latin-400-normal.woff2') format('woff2');
      unicode-range: U+0000-00FF, U+0131, U+0152-0153, ... U+FFFD;
  }
  ```
  ```css
  /* ui/web_new_v2/css/tokens.css:100-101 */
  --font-display: 'Sora', 'Plus Jakarta Sans', system-ui, -apple-system, sans-serif;
  --font-body: 'DM Sans', 'Segoe UI', system-ui, -apple-system, sans-serif;
  ```
  ```html
  <!-- ui/web_new_v2/index.html:2 -->
  <html lang="ru" data-theme="dark" data-progress-style="bars">
  ```
  Visual confirmation: `docs/screenshots/ui-v2-20261014/browser/home-1100.png` — the Latin "NeDotify" wordmark is set in the display face, while the Russian heading "Добрый день, Артур" next to it is set in the system face.
  Asset list: `assets/fonts/` contains 6 files, all `-latin-` or `-latin-ext-`; no `cyrillic` subset exists.
- **Reproduction / verification:** `Select-String -Path ui/web_new_v2/css/fonts.css -Pattern 'unicode-range'` → 6 ranges, none containing `U+04`; `Get-ChildItem ui/web_new_v2/assets/fonts` → 6 files, no Cyrillic cut. Runtime: DevTools → Rendering → *Fonts*, or `document.fonts.check('16px Sora', 'Привет')` → `false`.
- **Suggested fix:** either (a) add a Cyrillic subset of a display face that has one (e.g. Inter, Manrope, Unbounded — all with `cyrillic` cuts) and switch `--font-display`/`--font-body` to it, or (b) accept the system face and **stop shipping 248 KB of fonts that only cover Latin metadata** — in which case remove `css/fonts.css` from the link list and drop `assets/fonts/` (a 248 KB payload + 6 requests saved).
- **Fix side effects:** (a) changes the typography of the whole Russian UI — a product decision, not a bug fix; (b) changes the look of artist/track names.
- **Discovered by:** B

---

#### F-WN-33-12  [P2] — 620 KB of dead assets ship in the installer: the 306 KB theme-thumbnail set, a 318 KB logo, and two 1 KB defaults

- **File:** `ui/web_new_v2/assets/theme-previews/*.png` (17 files), `ui/web_new_v2/assets/logo.png`, `ui/web_new_v2/assets/artist_default.png`, `ui/web_new_v2/assets/playlist_default.png`; referenced only at `ui/web_new_v2/js/settings-view.js:13` (unreachable branch)
- **Confirmed:** yes
- **Description:** the whole `ui/web_new_v2/assets` tree (9,736,340 B) is bundled by `setup_pyinstaller.spec:27`. Four groups inside it are unreachable at runtime:
  - `assets/theme-previews/*.png` — 313,370 B across 17 files. The only reference is the `||` fallback in `js/settings-view.js:13`, which `window.NeDotifyAssets.themePreviewPath(id)` always pre-empts for all 22 preset ids (the `themes` map in `appearance-assets.js:5-28` contains every id in `settings-view.js`'s `THEME_IMAGES`, `settings-view.js:4-11`). The `docs/UI_V2_SETTINGS.md:5` description of these files as the delivered thumbnails is stale.
  - `assets/logo.png` — 318,664 B at 736×735. `index.html` uses `logo.png` (the 256×256, 57,931 B file in `ui/web_new_v2/`, not this one) for the favicon, the splash and the title bar; `assets/logo.png` is referenced by nothing.
  - `assets/artist_default.png` (1,524 B) and `assets/playlist_default.png` (1,143 B) — referenced by nothing (`assets/default_cover.png` *is* used, `index.html:1944`).
- **Cause:** assets are added to the tree and bundled wholesale (`setup_pyinstaller.spec:27` copies the entire directory) without a reference check.
- **Trigger conditions:** every install and every start (the files are extracted from the PyInstaller archive to `sys._MEIPASS`).
- **User impact:** 634,701 B (620 KB) of the installer payload is dead weight, and the 736×735 logo is a 318 KB PNG that would cost 4 KB at 64×64.
- **Evidence:**
  ```js
  // ui/web_new_v2/js/settings-view.js:12-14
  export function themePreviewPath(id) {
      return window.NeDotifyAssets?.themePreviewPath(id) || (THEME_IMAGES[id] ? `assets/theme-previews/${THEME_IMAGES[id]}.png` : '');
  }
  ```
  ```js
  // ui/web_new_v2/js/appearance-assets.js:46-50 — always returns a non-empty path for the 22 preset ids
  window.NeDotifyAssets = Object.freeze({
      resolveBackground,
      themePreviewPath: id => themes[id] ? localPath(`photo-${themes[id]}`) : '',
      backgroundPaths: Object.freeze([...photos].map(localPath))
  });
  ```
  Reference sweep over `ui/web_new_v2/**` for `logo.png|artist_default|playlist_default|theme-previews` → only `index.html:20,58,84` (`logo.png`, resolving to `ui/web_new_v2/logo.png`), `index.html:1944` (`assets/default_cover.png`) and `js/settings-view.js:13`.
- **Reproduction / verification:** `Get-ChildItem ui/web_new_v2/assets -Recurse -File | Where-Object { $_.Length -gt 100000 }` → `logo.png` 318,664 B; `Get-ChildItem ui/web_new_v2/assets/theme-previews` → 17 files, 313,370 B; `grep -rn "artist_default\|playlist_default\|assets/logo.png" ui/` → no hits.
- **Suggested fix:** delete the dead files (or wire the theme-previews PNGs back in, per F-WN-33-2) and add a test that asserts every file under `ui/web_new_v2/assets` is referenced by a stylesheet, an HTML file or a JS string.
- **Fix side effects:** none functionally; if the 17 PNGs are the desired thumbnails, F-WN-33-2 must be fixed instead of deleting them.
- **Discovered by:** B

---

#### F-WN-33-13  [P2] — The CSS architecture record is wrong in five load-bearing places, including the statement that `themes.css` must stay last

- **File:** `ui/web_new_v2/css/styles.css:4-15` (`~194 KB`), `:28` (`themes.css — MUST stay last`), `:33-39` ("visual-polish.css … currently dead"), `ui/web_new_v2/css/components/base.css:129` ("visual-polish.css, which index.html does not link"), `ui/web_new_v2/css/themes.css:16-18` ("Because index.html links themes.css LAST, that block silently won")
- **Confirmed:** yes
- **Description:** the file that exists to document the cascade states, in the current tree:
  1. *"Adding this file on top would fetch the same **~194 KB** of CSS a second time"* — the actual linked total is **416.8 KB** (426,845 B). The number is more than 2× stale.
  2. *"AUTHORITATIVE LOAD ORDER … 9. css/themes.css  theme overrides — **MUST stay last**"* — `index.html` links **12 more stylesheets after `themes.css`** (lines 35–46), and `themes.css` is at position 9 of 25. This is the exact mechanism that produces F-WN-33-1.
  3. *"ON components/visual-polish.css … index.html does NOT link it, so in the shipped app it is currently dead"* — `index.html:45` links it.
  4. `base.css:129`: *"It used to live only in components/visual-polish.css, which index.html does not link"* — it is linked at `index.html:45`, and the `--ring` token is therefore declared **twice** (`base.css:133` and `visual-polish.css`).
  5. `themes.css:16-18`: *"Because index.html links themes.css LAST, that block silently won"* — it is not last.
  Additionally `styles.css:52-69` `@import`s 18 files, 8 of which (`home-refresh`, `search-refresh`, `library-refresh`, `downloads-view`, `smart-playlists`, `feature-tools`, `settings-refresh`, `profile-refresh`, `window-resize`, `visual-polish`) are **not** in the "AUTHORITATIVE LOAD ORDER" list, and `onboarding.css` / `ui-style-picker.css` / the four `MACos_ui/*` files are missing from the `@import` list entirely even though they are linked.
- **Cause:** the document was written once and never updated; `tools/bench/css_inventory.py` still treats `styles.css` as the entrypoint and hard-codes an `IMPORT_ORDER` that mirrors it (as `styles.css:41-45` itself admits), so the tooling inherits the same stale order.
- **Trigger conditions:** always.
- **User impact:** the only written description of the CSS architecture tells a maintainer the opposite of the truth on the single most important invariant (where the theme overrides sit). This is the mechanism behind F-WN-33-1 and F-WN-33-7.
- **Evidence:** the five quoted statements above, checked against `ui/web_new_v2/index.html:17-50`.
- **Reproduction / verification:** `grep -c 'rel="stylesheet"' ui/web_new_v2/index.html` → 25; `grep -n 'themes.css' ui/web_new_v2/index.html` → line 28, with 12 further `<link>` lines after it; sum the 25 href sizes → 426,845 B.
- **Suggested fix:** regenerate `styles.css` from `index.html` (a 10-line script) and make it a *generated* file, or delete it and put the real order in `index.html` next to the links. Delete the "MUST stay last" claim or make it true.
- **Fix side effects:** none; the file is not loaded.
- **Discovered by:** B

---

#### F-WN-33-14  [P3] — No licence file for the bundled OFL webfonts; the artwork provenance record has no licence or author field

- **File:** `ui/web_new_v2/assets/fonts/` (6 WOFF2, 248,544 B), `ui/web_new_v2/assets/backgrounds/SOURCES.json:1-4`, `ui/web_new_v2/assets/theme-previews/`
- **Confirmed:** yes
- **Description:** DM Sans and Sora are distributed under the SIL Open Font License, which requires the licence to be distributed with the font. The `assets/fonts/` folder contains only the six `.woff2` files — no `OFL.txt`, no `LICENSE`, and no licence file anywhere else in the shipped tree (the retired `backups/retired-ui-v3/public/licenses/` folder had `Manrope-OFL.txt`, `Lucide-ISC.txt`, `HLS-Apache-2.0.txt`; the current tree ships `js/lucide.min.js` and `js/hls.min.js` with no licence text either — that part is outside this area). `assets/backgrounds/SOURCES.json` records `provider`, `usage`, and per-file `source` + `sha256` — I verified all 27 sha256 checksums match and every JPEG on disk is listed — but it records **no licence terms, no photographer/author and no Unsplash API/attribution reference**. The 17 `theme-previews/*.png` have no provenance record at all beyond `docs/UI_V2_SETTINGS.md:5` ("17 оригинальных PNG из пользовательского `NeDotify_17_theme_images.zip`").
- **Cause:** assets were vendored without a licence manifest, and the existing manifest was scoped to integrity (checksums) rather than licensing.
- **Trigger conditions:** every distribution of the installer.
- **User impact:** a redistribution-compliance gap in a product that is being installed on users' machines; the font licence is the clearest one (OFL §1 requires the licence to accompany the font).
- **Evidence:**
  ```json
  { "provider": "Unsplash",
    "usage": "Bundled desktop wallpaper and theme previews; original image bytes.",
    "images": [ { "file": "...", "source": "https://images.unsplash.com/...", "sha256": "..." } ] }
  ```
  `Get-ChildItem ui/web_new_v2/assets/fonts` → 6 files, all `.woff2`; `Get-ChildItem -Recurse -Include *OFL*,*LICENSE*` over the repo → only `.agents/skills/frontend-design/LICENSE.txt` (a skill file) and the retired `backups/retired-ui-v3/…` copies.
- **Reproduction / verification:** the checksum verification script (all 27 entries match, 0 mismatches, 0 unlisted files) — that part is clean; the absence of any `license` key in `SOURCES.json` and of any OFL text in `assets/fonts/` is the gap.
- **Suggested fix:** add `assets/fonts/OFL.txt` (the SIL OFL 1.1 text) and a `SOURCES.json` field recording the licence and author for each asset; add the same for `js/lucide.min.js` (ISC) and `js/hls.min.js` (Apache-2.0) even though those files live in the JS area.
- **Fix side effects:** none functionally; ~4 KB of text in the installer.
- **Discovered by:** B

---

#### F-WN-33-15  [P3] — `will-change` is applied to a class that no longer exists and to a `display:none` canvas; 442 `!important` declarations are the de-facto cascade arbiter

- **File:** `ui/web_new_v2/css/components/base.css:1742` (`.particle { will-change: transform; }`), `:3360` (`#home-visualizer-canvas { will-change: contents; }`), `:240` (`#visualizer-canvas, #home-visualizer-canvas { will-change: transform; }`), `css/components/home-refresh.css:81` (`#home-visualizer-canvas { display: none; }`), `css/components/lyrics.css:138` (`.lyric-line.active { will-change: transform, filter; }`)
- **Confirmed:** yes for the dead rules; the `will-change: contents` validity question is noted as a hypothesis
- **Description:** the particle system was rewritten to a canvas (`js/particles.js:301-306`), so the DOM class `.particle` no longer exists — `base.css:1742` is dead. `#home-visualizer-canvas` is `display: none` (`home-refresh.css:81`) yet still carries two `will-change` declarations (`base.css:240,3360`); `will-change: contents` is not a valid `will-change` value in CSS Will Change Level 1 (it is a Level-2 proposal) and, even if honoured, promoting a hidden element is pointless. Elsewhere the pattern is correct (`will-change: auto` resets at `base.css:3392`, `lyrics.css:88,393,440,474`).
- **Cause:** the CSS was not pruned when the particle and visualizer implementations changed; `will-change` is applied per component without a central rule.
- **Trigger conditions:** always (the declarations are parsed and the elements are matched at style-resolution time).
- **User impact:** minor GPU-memory waste from unnecessary layer promotions; a maintenance trap because a dead `.particle` rule suggests a DOM implementation that no longer exists.
- **Evidence:**
  ```css
  /* ui/web_new_v2/css/components/base.css:1741-1743 */
  .particle {
      will-change: transform;
  ```
  ```css
  /* ui/web_new_v2/css/components/base.css:3359-3361 */
  #home-visualizer-canvas {
      will-change: contents;
  ```
  ```css
  /* ui/web_new_v2/css/components/home-refresh.css:81 */
  #home-visualizer-canvas { display: none; }
  ```
  `grep -rn 'class="particle' ui/web_new_v2/index.html` → no hits; `js/particles.js:301-306` creates `<canvas id="particles-canvas">`, not `.particle` elements.
- **Reproduction / verification:** `grep -n 'class="particle' ui/web_new_v2/index.html` (no hits) and `grep -n 'particle' ui/web_new_v2/js/particles.js` (canvas only).
- **Suggested fix:** delete `base.css:1741-1743` and `base.css:3359-3361`; keep `will-change` only on elements that actually animate, and always pair it with a `will-change: auto` reset.
- **Fix side effects:** none expected; verify that the home visualizer is genuinely retired before removing `will-change: transform` from `base.css:240`.
- **Discovered by:** B

---

#### F-WN-33-16  [P3] — `test_frontend_css_wiring.py` does not cover `ui/MACos_ui/**` and does not check the theme-override invariant

- **File:** `tests/test_frontend_css_wiring.py:63-70` (`css_files_on_disk` walks `CSS_DIR` only), `:135-151` (`test_polish_layer_is_linked_last`)
- **Confirmed:** yes
- **Description:** the file whose stated purpose is *"Static checks that every shipped stylesheet is actually applied"* only walks `ui/web_new_v2/css` (`CSS_DIR`, line 35). The four `ui/MACos_ui/*.css` files (72,481 B) are outside that tree and are therefore **never** checked for being linked — deleting `index.html:47-50` would leave the test suite green while the macOS presentation pack silently dies. Symmetrically, `test_polish_layer_is_linked_last` explicitly *permits* the four `MACos_ui` sheets to follow `visual-polish.css` and only asserts `themes.css < visual-polish.css` — it never asserts that no sheet loaded after `themes.css` re-declares a palette token, which is precisely the hole F-WN-33-1 falls through.
- **Cause:** the test was written for the regression it was created for (the unlinked `visual-polish.css`) and generalised only as far as the original `css/` directory.
- **Trigger conditions:** always.
- **User impact:** the "is the CSS actually wired up?" guarantee covers 21 of the 25 linked stylesheets; a fourth of the cascade is unguarded.
- **Evidence:**
  ```python
  # tests/test_frontend_css_wiring.py:34-36, 63-70
  UI_DIR = os.path.join(PROJECT_ROOT, "ui", "web_new_v2")
  CSS_DIR = os.path.join(UI_DIR, "css")
  ...
  def css_files_on_disk():
      found = set()
      for dirpath, _dirnames, filenames in os.walk(CSS_DIR):
          if name.endswith(".css"):
              found.add(os.path.normpath(os.path.join(dirpath, name)))
      return found
  ```
  ```python
  # tests/test_frontend_css_wiring.py:148-151
  assert order[polish_positions[-1] + 1:] == [
      'css/components/ui-style-picker.css', 'MACos_ui/tokens.css', 'MACos_ui/interface.css', 'MACos_ui/settings.css', 'MACos_ui/library.css'
  ], 'Only the shared style picker and scoped presentation pack may follow polish'
  assert order.index('css/themes.css') < polish_positions[-1]
  ```
- **Reproduction / verification:** `pytest tests/test_frontend_css_wiring.py -q` → green, while the macOS pack is unverified; removing the four `MACos_ui` links from `index.html` and re-running the test still passes.
- **Suggested fix:** extend `css_files_on_disk()` to walk `ui/` (both `web_new_v2/css` and `MACos_ui`), and add a test that asserts no stylesheet linked after `themes.css` declares a raw-palette token (the F-WN-33-1 detector).
- **Fix side effects:** the extended walk will flag `ui/MACos_ui/tokens.css` (it legitimately re-declares palette tokens under the `[data-ui-style="macos"]` scope) — the allow-list must be scope-aware, not path-aware.
- **Discovered by:** B

---

### 3. Clean areas

- **No external `url()` anywhere in the CSS.** Every `url()` in the 25 linked stylesheets is a local relative path — and there are only **nine** of them in total: the six `../assets/fonts/*.woff2` (`css/fonts.css:48,57,69,78,88,97`), `../assets/backgrounds/photo-1519681393784-d120267933ba.jpg` (`ui/MACos_ui/library.css:60`), `assets/atmosphere-dusk.png` (`ui/MACos_ui/interface.css:11`), `assets/library-wave.svg` (`ui/MACos_ui/library.css:64`). There is **no** remote stylesheet, no CDN font, no tracking pixel, no `data:` URI and no `javascript:` URL. The self-hosting of the webfonts (`css/fonts.css:5-12` explains the move away from `fonts.googleapis.com`) is complete and correct.
- **No legacy CSS script vectors.** No `expression(...)`, no `behavior:`, no `-moz-binding`, no `@import` of a remote sheet anywhere in the linked set. (The `behavior:` matches a naive grep are the modern `overscroll-behavior: contain/smooth/auto` property — `base.css:2165`, `lyrics.css:24`, `home-refresh.css:162,245`, `search-refresh.css:120`, `library-refresh.css:26,33,189`, `settings-refresh.css:16,25`, `onboarding.css:48`, `MACos_ui/interface.css:147,289` — all legitimate.)
- **The CSP is tight.** `ui/web_new_v2/index.html:10` keeps `script-src 'self'`, `object-src 'none'`, `base-uri 'none'`, `form-action 'none'`. The only external origins still allowed are `style-src https://fonts.googleapis.com` and `font-src https://fonts.gstatic.com` — both now **vestigial**, since the fonts are self-hosted (`css/fonts.css:5-12`). Removing those two origins would close the last external surface; `img-src`/`media-src`/`connect-src` legitimately need `https:` for the music providers.
- **`assets/backgrounds/SOURCES.json` is complete and accurate.** All 27 JPEGs on disk are listed, the counts match, and **every one of the 27 sha256 checksums verifies**. The manifest is a genuine integrity record — it just lacks the licence/author fields (F-WN-33-14).
- **The `blur-out` IntersectionObserver exists and works** for the four classes it covers (`ui/web_new_v2/js/efficiency.js:4-73` + `css/components/base.css:287-294`); the design intent is right, only the coverage is too narrow (F-WN-33-5).
- **The macOS presentation pack is not dead code.** `ui/MACos_ui/**` is loaded by `index.html:47-50`, is reachable at runtime through the six Bottle routes installed by `core/ui_assets.py:19-22`, and is toggled by `ui/web_new_v2/js/ui-style.js:68-126` (`data-ui-style="macos"`). The brief's assumption that it is a legacy pack to be deleted is incorrect — it is the live alternative style.
- **The macOS pack's relative asset references resolve correctly.** `ui/MACos_ui/library.css:60` uses `url("../assets/backgrounds/photo-…jpg")`, which from `/MACos_ui/library.css` resolves to `/assets/backgrounds/…` — the `ui/web_new_v2/assets` tree, which is exactly where the file lives. No 404.
- **The only six `@font-face` rules in the whole UI tree are in `css/fonts.css:43,52,64,73,83,92`** — DM Sans (roman/italic × latin/latin-ext) and Sora (latin/latin-ext). No other stylesheet declares a face, so the webfont surface is small and auditable.
- **The font subsetting is correct and the `unicode-range` split is deliberate** (`css/fonts.css:20-24` explains why the per-subset split must be kept). The faces are variable fonts with an `fvar` table, so six files cover the whole requested weight axis. The only issue is the missing Cyrillic cut (F-WN-33-11), which the file itself documents as a conscious decision.
- **The performance presets are well designed.** `:root.perf-medium` / `:root.perf-low` / `:root.battery-saver-active` (`base.css:159-227`) zero every blur/glow token and disable transitions and animations in one place, and `js/efficiency.js` + `body.unfocused-blur-disabled` (`base.css:3083`) extend it to the unfocused state. The mechanism works; it is the *default* cost profile that is too high (F-WN-33-5/6), not the escape hatch.
- **The `will-change` reset pattern is used correctly where it matters** — `lyrics.css:393,440,474` and `base.css:3392` reset to `auto` once the animation is over, which is the textbook fix for the "permanent layer promotion" problem.

---

### 4. Coverage gaps

- **No runtime measurement of the render cost.** I could not launch the app (the audit rules forbid running the real app, and the bench harness needs a GUI WebView2 + a CDP port). The `backdrop-filter` count, the `filter: blur()` count and the asset byte counts are exact and static, but the *frame-rate / CPU* consequence (F-WN-33-5, F-WN-33-6) is a hypothesis. **What would confirm it:** `python tools/bench/run_bench.py --scenario cpu_attribution --tracks 2000 --seconds 8` with `optimization_performance_preset` = `high` vs `low`, comparing the renderer-process CPU; the repo already has the harness and the `optimization-before-20261015-154303.json` baseline to compare against.
- **The lazy-loading behaviour of the 44 theme-preview `<img>` elements is not measured.** I confirmed the DOM insertion at boot and the byte counts, but not whether Chromium's lazy loader actually fetches the 1600-px JPEGs while the settings overlay is `visibility: hidden`. **What would confirm it:** DevTools → Network with the cache disabled, opening the app and the Settings view, and counting `assets/backgrounds/*.jpg` transfers.
- **The pixel-regression question is unanswerable as the repo stands.** `tools/visual_guard/goldens/` is empty and the capture path needs a GUI + CDP (`capture.py:83-120`), so I could not determine what the UI looked like before/after the `home-refresh.css` override beyond the stale screenshots in `docs/screenshots/` (which are purple, i.e. pre-override). **What would confirm it:** `--capture` on a developer machine, then `--compare`.
- **The `tools/bench/css_inventory.py` inventory and its `IMPORT_ORDER` are stale by construction** (`css/styles.css:41-45` says so explicitly). I did not audit `tools/bench/**` (WN-35) and did not verify the numbers in `tools/bench/results/css_blur_map.json` (81 blur declarations, measured 2026-10-04 against a 9-file CSS set) — the current tree measures 76 `backdrop-filter` + 86 `filter: blur()` declarations, so that artefact no longer describes the tree.
- **I did not measure the DOM-level impact of the 27 backdrop-filtered surfaces.** `tools/bench/results/backdrop_nesting.json` reports `records: 60, max_nesting_depth: 1, records_with_backdro_filtered_ancestor: 29` — i.e. 29 backdrop-filtered elements sit inside another backdrop-filtered ancestor, which in Chromium forces a containing block and a second blur pass — but that artefact is from 2026-10-04 and predates the current 25-sheet set.
- **Font-rendering quality / FOUT was judged from the static `unicode-range` and from the reference screenshots, not from a live trace.** I did not capture a `document.fonts` timing trace.
- **The `MACos_ui` pack's runtime cost was sized statically only** (21 `backdrop-filter` declarations, 14 of them `none`; the 1.36 MB PNG backdrop with a `saturate() blur()` filter over the full viewport). I did not measure it in the macOS style.
- **I did not review the JS that consumes the CSS** (`js/settings.js`, `js/ui-style.js`, `js/appearance-assets.js`, `js/efficiency.js`) beyond what was needed to establish the CSS contract; the JS-side defects (e.g. the 44 preview `<img>` elements created at boot) are attributed to **WN-30**.
- **`ui/web_new_v2/css/components/*.css` was machine-scanned in full but manually read only for base.css, home-refresh.css, tokens.css, themes.css, fonts.css, styles.css, window-resize.css and ui-style-picker.css.** The other 13 component sheets were verified by machine scan (selectors, declarations, `url()`, `!important`, `backdrop-filter`, `will-change`, raw colours) and by targeted reads of every filter/blur site, but their prose comments and their non-filter rules were not read line by line.

---

### 5. Architecture improvements (ARCH)

**ARCH-1 — Collapse the 25 render-blocking stylesheets into a 3–4 sheet cascade with a documented, enforced order.**
`index.html` links 21 `web_new_v2/css/**` sheets + 4 `MACos_ui/**` sheets = 416.8 KB, all blocking. The split was motivated by authoring convenience, but nothing enforces the order and the order is load-bearing in at least three places (F-WN-33-1, F-WN-33-7, F-WN-33-13). A target of **4 blocking sheets** — `fonts.css` (5 KB), `tokens.css` (8 KB), `base.css` (129 KB), `themes.css` (15 KB) — plus **per-view sheets loaded on demand** would cut the blocking payload from 416.8 KB to ~157 KB. The order must then be a machine-readable contract, not a comment.

**ARCH-2 — Make `base.css` a real base and let the `*-refresh.css` sheets own only their view.**
The two-system situation (F-WN-33-7) is the classic "I changed it and nothing happened" generator: 99 duplicated selectors, 200 conflicting property values, 442 `!important`. The correct end state is: `base.css` owns every element rule; each `*-refresh.css` owns only the *new* selectors it introduces and the *new* properties for its view. The 69 conflicting selectors are the migration backlog; a conflict-detector test that fails while the count is > 0 makes the backlog visible and shrinkable.

**ARCH-3 — One owner per token, enforced by a test rather than by prose.**
`tokens.css:8-31` states the single-ownership rule; `base.css:113-125` breaks it for 10 tokens (F-WN-33-8), `themes.css` owns the palette but `home-refresh.css` overrides it (F-WN-33-1), and `MACos_ui/tokens.css` re-declares 26 of them under a scope. A single test — "a custom property is declared in exactly one file per scope" — would have caught both.

**ARCH-4 — Move the macOS pack inside the served root, or make its reachability a first-class contract.**
`ui/MACos_ui/` is a *sibling* of `ui/web_new_v2/`, but the page's static root is `ui/web_new_v2` (pywebview roots the Bottle server at the window URL's directory). The pack is therefore reachable **only** because `core/ui_assets.py:19-22` hand-registers six routes for it — a Python module and an HTML `<link>` list that must agree, with no test covering the agreement (F-WN-33-16). Moving the pack to `ui/web_new_v2/macos/` (or into `css/packs/macos/`) removes the cross-directory coupling and lets the existing wiring test cover it.

**ARCH-5 — Give the visual guard a real gate: goldens + a repo-root CSS-guard test.**
Today the pixel half is a vacuous pass (0 goldens → `ok: true`, F-WN-33-9) and the CSS half is red but unwatched (F-WN-33-9, F-WN-33-10). The cheapest high-value step is not the 96 golden PNGs — it is (a) making `compare_sets` fail on an empty goldens directory, (b) adding a pytest that runs `css_declaration_guard()` against the repo root, and (c) extending the guard's key to `file|selector|property` and its watched set to the palette tokens. Those three changes would have caught F-WN-33-1 and most of F-WN-33-7.

**ARCH-6 — Introduce an asset pipeline for the wallpapers and the theme thumbnails.**
The UI has 27 wallpapers at 1600 px, 17 purpose-built 185×58 thumbnails that are never used, a 736×735 logo that nothing references, and a 1727×910 PNG backdrop — 10.6 MB of hand-curated binary in the installer with no derivative step, no size budget and no format negotiation (F-WN-33-3, F-WN-33-12). A build step that produces 256/512/1920-px WebP derivatives of the wallpapers, a 200-px WebP thumbnail per theme, and a 32-px favicon would cut the imagery payload to ~1.5 MB and make the thumbnail slot correct by construction.

**ARCH-7 — Budget the render cost, not just the payload.**
27 always-on backdrop-filter surfaces and a full-viewport 8 px blur on an animating canvas (F-WN-33-5, F-WN-33-6) is not a payload problem, it is a frame-budget problem. A cheap, concrete guard: a lint rule that fails when more than N selectors in the shared layer carry an active `backdrop-filter`, and a rule that forbids `filter: blur()` on a container that holds a `<canvas>`. The `perf-low` preset already proves the flat look is shippable; making "no blur" the default on low-end GPUs (detected once, not per element) would be cheaper than the current per-element machinery.

**ARCH-8 — Decide the typography once, and let the token system express it.**
The app is Russian; the bundled fonts are Latin-only (F-WN-33-11); the macOS pack overrides `--font-body`/`--font-display` with a system stack (`MACos_ui/tokens.css:47-49`); and the Settings panel offers 31 font choices (`js/settings.js:517-561`) of which **not one** is a bundled webfont — the six shipped faces (DM Sans, Sora) are not even in the list, while entries like 'Inter', 'Outfit', 'Montserrat' and 'Plus Jakarta Sans' are named without any `@font-face` and are not installed on Windows, so selecting one silently falls back to the next family in the stack. That last point is a concrete defect the CSS layer can express: a font token that names a family with no `@font-face` and no system presence is a lie. Either bundle the offered families or restrict the list to the ones that resolve.
