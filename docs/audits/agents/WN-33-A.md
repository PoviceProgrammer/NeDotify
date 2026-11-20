## AREA WN-33 — UI styling: themes, tokens, component CSS, legacy CSS pack — ROLE A

### 1. Scope reviewed

**Files opened (path: line ranges actually read)**

| File | Range read |
|---|---|
| `ui/web_new_v2/index.html` | 1–120 (head + all `<link>`/`<script>` tags) |
| `ui/web_new_v2/css/tokens.css` | 1–180 (whole file) |
| `ui/web_new_v2/css/themes.css` | 1–422 (whole file) |
| `ui/web_new_v2/css/fonts.css` | 1–99 (whole file) |
| `ui/web_new_v2/css/styles.css` | 1–69 (whole file) |
| `ui/web_new_v2/css/components/base.css` | 112–127, 255, 301–310, 489–520, 586, 822, 906, 1399, 1426, 1462, 1852, 1935, 2071, 2186, 2239, 2345, 2536, 2805–2825, 3114, 3371–3372, 3684, 4068–4107, 4234, 4252, 4267, 4321, 4424–4427 (spot reads + full var/selector sweeps) |
| `ui/web_new_v2/css/components/player-bar.css` | 1–120, 690–747 |
| `ui/web_new_v2/css/components/player-view.css` | 83–93 |
| `ui/web_new_v2/css/components/home-refresh.css` | 1–60, 148, 162–249 |
| `ui/web_new_v2/css/components/search-refresh.css` | 64–67, 119 |
| `ui/web_new_v2/css/components/library-refresh.css` | 64, 119–124, 188 |
| `ui/web_new_v2/css/components/settings-refresh.css` | 84, 108, 172 |
| `ui/web_new_v2/css/components/onboarding.css` | 2–122 (all `--ob-*` rules) |
| `ui/web_new_v2/css/components/visual-polish.css` | 204 |
| `ui/web_new_v2/css/components/downloads-view.css`, `smart-playlists.css`, `feature-tools.css`, `profile-refresh.css`, `ui-style-picker.css`, `window-resize.css`, `home-view.css`, `track-table.css`, `lyrics.css` | full-file var/selector/`url()` sweeps + targeted reads |
| `ui/MACos_ui/tokens.css` | 1–119 (whole file) |
| `ui/MACos_ui/interface.css` | 1–30, 288 (whole-file sweep) |
| `ui/MACos_ui/library.css` | 60, 64, 72, 76 |
| `ui/MACos_ui/settings.css` | 37–40, 89–98 |
| `ui/web_new_v2/js/ui-style.js` | 1–294 (whole file) |
| `ui/web_new_v2/js/settings-view.js` | 1–80 |
| `ui/web_new_v2/js/settings.js` | 20–99, 470–609, 601–645, 700–759, 1680–1739, 1820–1889 |
| `ui/web_new_v2/js/appearance-assets.js` | 1–51 (whole file) |
| `ui/web_new_v2/js/onboarding.js` | 1–60, 85–144 |
| `ui/web_new_v2/js/boot.js` | 1–40 |
| `core/ui_assets.py` | 1–22 (whole file) |
| `core/settings.py` | 52, 177–193, 553–561 |
| `main.py` | 50–109, 330–459 |
| `setup_pyinstaller.spec` | 1–95 (`extra_datas`) |
| `tools/bench/css_inventory.py` | 49–66, 383–466 |
| `tests/test_macos_ui.py` | 1–163 (whole file) |
| `ui/web_new_v2/assets/backgrounds/SOURCES.json` | 1–141 (whole file) |

**Automated sweeps run (read-only, scripts written under `%TEMP%`)**
- `var(--x)` usage vs `--x:` definition cross-check over all 28 CSS files in `ui/web_new_v2/css/**` + `ui/MACos_ui/**` (including a separate pass for "used but never defined" and "defined but never used").
- Full CSS parser (media-context aware) that re-parses every rule, splits selector lists at parenthesis depth 0, computes selector specificity and `!important`, and resolves the effective winner using the **real `<link>` order from `index.html`**.
- `url()` extraction + on-disk existence check for every referenced asset.
- SHA-256 re-verification of all 27 `SOURCES.json` entries against the shipped JPEGs.
- Bottle/pywebview route-resolution trace to determine whether the `ui/MACos_ui/**` pack is reachable at runtime.

**Callees traced into other areas (not double-reported here)**
- `js/ui-style.js` (theme/style switcher) → **WN-30** owns it. CSS-side facts about it are reported here; the JS defects themselves are not.
- `js/settings.js` (`applyThemeMode`, `PRESET_THEMES`, `CUSTOM_COLOR_PROPS`, `THEMES`) → **WN-30**.
- `js/appearance-assets.js` / `js/settings-view.js` (theme preview resolution) → **WN-30**.
- `core/ui_assets.py` (legacy pack HTTP routes) → **WN-16**; verified here only for "is the pack reachable".
- `main.py` (window URL / route installation) → **WN-01**; the `ui_style`/`macos_mode` persistence round-trip → **WN-08 / WX-03**.
- `tools/bench/css_inventory.py` → **WN-35**.

---

### 2. Findings

#### F-WN-33-1  [P1] — `home-refresh.css` re-declares the global `dark` theme palette, killing `themes.css`'s Dark theme and the glass/translucent look of the default theme

- **File:** `ui/web_new_v2/css/components/home-refresh.css:12-24` (also `ui/web_new_v2/css/themes.css:68-83`, `ui/web_new_v2/index.html:28` vs `:35`)
- **Confirmed:** yes
- **Description:** `home-refresh.css` — a *component* file — declares its own `:root[data-theme="dark"]` palette block that redefines the global raw palette (`--bg-main`, `--bg-surface`, `--bg-card`, `--primary`, `--primary-rgb`, `--primary-fg`, `--accent`, `--accent-glow`, `--ambient-glow`, `--text-sec`, `--text-dim`). `themes.css` owns that palette by contract, and it is linked **before** `home-refresh.css`. Both selectors have identical specificity `(0,2,0)`, so the later stylesheet wins: the app's "Dark" theme renders with the green palette from `home-refresh.css` and the documented violet/near-black Dark theme in `themes.css` is dead code. In addition, `home-refresh.css` sets `--bg-card: #12382d` and `--bg-surface: #0c241c` — **opaque** values — where the theme system uses translucent ones, which removes the glass effect for every card in the app.
- **Cause:** A component stylesheet re-declares theme-scoped raw-palette tokens. This is exactly the class of bug the `tokens.css` ownership split was written to prevent (`tokens.css:17-23`: *"every name below is declared EXACTLY ONCE in the whole stylesheet set"*), and the documented guarantee that the outcome is "order-independent" is broken by it.
- **Trigger conditions:** Any run of the app with `data-theme="dark"` — which is the shipped default (`index.html:2`, `core/settings.py:178` `"theme": "dark"`, `core/settings.py:193` `"theme_mode": "dark"`). Also triggered whenever the user picks the "Тёмная"/Dark mode button (`js/settings.js:1718` → `applyThemeMode('dark')` → `data-theme='dark'`, `js/settings.js:1844`).
- **User impact:** The default theme is a dark-green/teal app, not the designed near-black + violet theme: accent `#18d6a2` instead of `#a855f7`, background `#061711` instead of `#0a0a0f`. Cards/panels become solid `#12382d` instead of translucent `rgba(255,255,255,0.03)`, so the "glassmorphism" system (`tokens.css:84-95`) and the custom-background see-through are lost app-wide. The theme picker's Dark preview swatch (`js/settings.js:493` `colors: ['#121212','#ffffff','#1e1e1e']`), the onboarding preview (`js/onboarding.js:6` `bg:'#0a0a0f', accent:'#a855f7'`) and the backend's default accent (`core/settings.py:561` `get("theme","accent_color","#a855f7")`) all still say violet/black — four sources disagree with what is rendered.
- **Evidence:**
  `ui/web_new_v2/css/themes.css:68-79`
  ```css
  :root[data-theme="dark"], [data-theme="dark"] {
      --bg-main: #0a0a0f;
      --bg-surface: #14141d;
      --accent: #a855f7;
      ...
      --primary: #a855f7;
      --primary-rgb: 168, 85, 247;
  ```
  `ui/web_new_v2/css/components/home-refresh.css:12-24`
  ```css
  :root[data-theme="dark"] {
      --bg-main: #061711;
      --bg-surface: #0c241c;
      --bg-card: #12382d;
      --primary: #18d6a2;
      --primary-rgb: 24, 214, 162;
      --primary-fg: #04261c;
      --accent: #18d6a2;
      --accent-glow: rgba(24,214,162,.16);
      --ambient-glow: rgba(24,214,162,.08);
      --text-sec: #adbfba;
      --text-dim: #839d95;
  }
  ```
  `ui/web_new_v2/index.html:28` and `:35`
  ```html
  <link rel="stylesheet" href="css/themes.css?v=20260827_blur">
  ...
  <link rel="stylesheet" href="css/components/home-refresh.css?v=20261014_home">
  ```
  Opaque `--bg-card` consumption: `ui/web_new_v2/css/components/base.css:906`, `:1426`, `:1462`, `:1852`, `:2071`, `:2186`, `:2345`, `:2536` all use `background: var(--bg-card);`.
- **Reproduction / verification:**
  1. Resolve the cascade by hand: both rules are `:root[data-theme="dark"]` → specificity `(0,2,0)`; `home-refresh.css` is `<link>`ed at `index.html:35`, after `themes.css` at `index.html:28` → `home-refresh.css` wins (CSS cascade: equal specificity → last in document order wins; `@media` does not change this).
  2. In DevTools on the running app: `getComputedStyle(document.documentElement).getPropertyValue('--primary')` → `rgb(24, 214, 162)` (green), not `rgb(168, 85, 247)`.
  3. `getComputedStyle(document.documentElement).getPropertyValue('--bg-card')` → `rgb(18, 56, 45)` (opaque), not `rgba(255, 255, 255, 0.03)`.
  4. Automated re-check: my parser (see §1) reports `--primary` for `:root[data-theme="dark"]` declared in `css/themes.css` (link #8) **and** `css/components/home-refresh.css` (link #9), with the latter as effective winner.
- **Suggested fix:** Delete the `:root[data-theme="dark"]` block from `home-refresh.css:12-24` (or move the palette into `themes.css` as a 23rd explicit theme id, e.g. `data-theme="forest"`, and add it to `PRESET_THEMES`). If the translucent look must survive, use `color-mix(... , transparent)` values instead of solid hex.
- **Fix side effects:** Removing the block changes the app's default appearance back to violet/near-black — the theme-picker preview PNGs/gradients, `js/settings.js:493` swatches and `core/settings.py:561` would then match the UI again, but any user who has come to expect green will see a different app. If instead a new theme id is introduced, `js/settings.js` (`PRESET_THEMES`) and `js/appearance-assets.js` (`themes` map) must be updated in the same change (WN-30) or the picker will show a broken card.
- **Discovered by:** A

---

#### F-WN-33-2  [P2] — `--player-bar-height` / `--player-bar-offset` are declared on `:root` four times; the responsive overrides in `player-bar.css` are dead and the documented 600 px overlap fix is regressed

- **File:** `ui/web_new_v2/css/components/home-refresh.css:9-10` (also `:206`, `:219`) vs `ui/web_new_v2/css/components/player-bar.css:33-39`, `:711`, `:729`; `ui/web_new_v2/index.html:23` vs `:35`
- **Confirmed:** yes
- **Description:** `player-bar.css` publishes the two layout tokens on `:root` (`:34-35` → `84px` / `20px`) and then overrides them **inside `@media` queries** (`:711` → `80px`/`16px` at ≤900 px; `:729` → `68px`/`72px` at ≤600 px). `home-refresh.css`, which is `<link>`ed later, re-declares the very same two properties on a plain `:root` (`:9-10` → `92px` / `16px`). A plain `:root` rule that appears *later in document order* outranks an `@media`-wrapped `:root` rule that appears *earlier*, because media queries do not contribute specificity. The result is that `player-bar.css`'s two breakpoint overrides are unreachable, and the `--player-bar-height` fallback `84px` used by eight call sites is also unreachable.
- **Cause:** The same layout token is published by two files with the same selector specificity; the winner is decided purely by `<link>` order, which is the exact "correctness was an accident of the link order" failure the `tokens.css` header warns about (`tokens.css:17-23`).
- **Trigger conditions:** Every render. The dead rules matter at the 600 px breakpoint, which is reachable: `main.py:374` sets `min_size=(600, 640)`, and `main.py:371` explicitly notes *"at 600px exactly the @media (max-width: 600px) rule still matches"*.
- **User impact:** The clearance contract documented in `player-bar.css:7-32` — *"the reserved space is a constant 32px at every breakpoint"* and *"at 600px wide the bar covered the last 24px of content"* — is no longer enforced by the token that was written to enforce it. At ≤600 px the effective values are `--player-bar-height: 108px` (`home-refresh.css:206`) and `--player-bar-offset: 70px` (`home-refresh.css:219`), whereas the bar itself is placed by `home-refresh.css:226` (`bottom: 70px`) with `height: 108px` (`home-refresh.css:205`) — i.e. two files now own the bar's geometry, and the file that documents the contract cannot change it. Any future edit to `player-bar.css`'s breakpoints will silently have no effect.
- **Evidence:**
  `ui/web_new_v2/css/components/player-bar.css:33-39`
  ```css
  :root {
      --player-bar-height: 84px;
      --player-bar-offset: 20px;
  ```
  `ui/web_new_v2/css/components/player-bar.css:710-711, 728-729`
  ```css
  @media (max-width: 900px) {
      :root { --player-bar-height: 80px; --player-bar-offset: 16px; }
  ...
  @media (max-width: 600px) {
      :root { --player-bar-height: 68px; --player-bar-offset: 72px; }
  ```
  `ui/web_new_v2/css/components/home-refresh.css:3-10`
  ```css
  :root {
      --home-panel: var(--bg-main);
      ...
      --player-bar-height: 92px;
      --player-bar-offset: 16px;
  }
  ```
  `ui/web_new_v2/css/components/home-refresh.css:205-206, 218-219`
  ```css
  #player-bar, html.has-custom-bg #player-bar { grid-template-columns: minmax(0,1fr) 215px; height: 108px; padding: 12px 14px; }
  :root { --player-bar-height: 108px; }
  ...
  :root { --player-bar-offset: 70px; }
  ```
  Load order: `index.html:23` (`player-bar.css`) → `index.html:35` (`home-refresh.css`).
- **Reproduction / verification:** In DevTools, `getComputedStyle(document.documentElement).getPropertyValue('--player-bar-height')` at a 900 px-wide window returns `92px` (not `80px`), and at 600 px returns `108px` (not `68px`). Resize the window to exactly 600 px (the app's `min_size` width) and compare with the rule at `player-bar.css:729`. Automated re-check: my cascade resolver reports `--player-bar-height` declared on `:root` in `css/components/player-bar.css` (link #3) and `css/components/home-refresh.css` (link #9); both have specificity `(0,1,0)`; the later one wins at every width.
- **Suggested fix:** Publish `--player-bar-height` / `--player-bar-offset` in exactly one place (a single `:root` block in `tokens.css` or `player-bar.css`) and let only that file carry the `@media` breakpoints; delete the duplicate `:root` block in `home-refresh.css:3-11` (or move its breakpoint overrides there with a higher-specificity selector such as `:root` inside the same file).
- **Fix side effects:** Removing `home-refresh.css:9-10` changes the reserved space from 92+16 to 84+20 px in the default layout, which shifts `#main-content`/`#sidebar` bottom margins by 6 px and the bar height by 8 px (`home-refresh.css:148` sets `height: var(--player-bar-height)`). The 760 px and 600 px breakpoints in `home-refresh.css` would then need to be reconciled with `player-bar.css`'s 900 px/600 px pair, otherwise the bar's height and the reserved space can drift apart again.
- **Discovered by:** A

---

#### F-WN-33-3  [P3] — `--focus` has no consumer in any stylesheet: the "focus colour" setting does nothing

- **File:** `ui/web_new_v2/js/settings.js:1653`, `:1733` (no CSS consumer anywhere in `ui/web_new_v2/css/**` or `ui/MACos_ui/**`)
- **Confirmed:** yes
- **Description:** The Appearance panel exposes a focus-colour picker bound to the custom property `--focus`. A full sweep of all 28 CSS files finds **zero** occurrences of `--focus` in any declaration and zero occurrences of `var(--focus)`. Every focus ring in the app is hard-coded to `var(--primary)` (e.g. `home-refresh.css:169` `button:focus-visible, [role="button"]:focus-visible, .clickable-artist:focus-visible { outline: 2px solid var(--primary); outline-offset: 3px; }`).
- **Cause:** The token was added to the custom-palette map without a matching CSS consumer, so `setCustomColor('focus', …)` writes a property nothing reads.
- **Trigger conditions:** User opens Settings → Appearance → "Цвет фокуса" and picks a colour.
- **User impact:** The picker appears to work (the swatch updates) but no focus ring in the app changes. A silent, no-op setting — exactly the failure mode the project brief calls out ("The failure mode here is silence").
- **Evidence:**
  `ui/web_new_v2/js/settings.js:1653`
  ```js
  const CUSTOM_COLOR_PROPS={primary:'--primary',accent:'--accent',bg:'--bg-main',text:'--text-main',card:'--bg-card',border:'--border',dim:'--text-dim',focus:'--focus'};
  ```
  `ui/web_new_v2/js/settings.js:1733`
  ```js
  { id: 'picker-color-focus', prop: '--focus' }
  ```
  CSS sweep result: `Select-String -Path "ui\web_new_v2\css\*.css","ui\web_new_v2\css\components\*.css","ui\MACos_ui\*.css" -Pattern "--focus"` → **0 matches**.
- **Reproduction / verification:** `Select-String -Path ui\web_new_v2\css\*.css,ui\web_new_v2\css\components\*.css,ui\MACos_ui\*.css -Pattern "--focus"` returns nothing; then in DevTools pick a focus colour and inspect any `outline` — it stays `var(--primary)`.
- **Suggested fix:** Either wire `--focus` into the focus-ring rules (`button:focus-visible`, `:focus-visible` outlines) or remove `focus` from `CUSTOM_COLOR_PROPS` and the picker row so the UI stops offering a dead control.
- **Fix side effects:** Wiring it in changes every focus ring across the app (accessibility-visible change); removing it removes a user-visible control from the Appearance panel.
- **Discovered by:** A (the JS-side picker is **WN-30**; the CSS-side fact — no consumer exists — is reported here)

---

#### F-WN-33-4  [P3] — Four "performance control" custom properties are declared but never read anywhere (CSS or JS)

- **File:** `ui/web_new_v2/css/components/base.css:120-122` and `:34`
- **Confirmed:** yes
- **Description:** `base.css` declares `--enable-transitions: 1`, `--enable-animations: 1`, `--enable-shadows: 1` (each with the comment *"Set to 0 to skip …"*) and `--bg-opacity: 1` at `base.css:34`. A sweep of all CSS files shows no `var(--enable-*)` / `var(--bg-opacity)` reference, and a sweep of `ui/web_new_v2/js/**` + `index.html` shows no `setProperty('--enable-…')` / `setProperty('--bg-opacity')`. The mechanism that was meant to let the performance preset switch animations/shadows off is inert; the real switch is the separate `perf-low` / `battery-saver-active` class path.
- **Cause:** The tokens were introduced as a generic "performance-controlled variables" API but were never wired to any rule or to the JS that would toggle them. (They are also duplicated in `tokens.css` for `--glass-blur`/`--blur-*`/`--player-glow-*`, i.e. two owners for the same names.)
- **Trigger conditions:** Always — the tokens are inert in every state.
- **User impact:** None directly (the `perf-low` class path works), but the tokens are a trap: setting `--enable-animations: 0` from a future settings toggle would silently do nothing.
- **Evidence:**
  `ui/web_new_v2/css/components/base.css:113-125`
  ```css
  :root {
      /* ── Performance-controlled variables ── */
      --glass-blur: 8px;          /* User-controlled backdrop blur */
      ...
      --enable-transitions: 1;    /* Set to 0 to skip slow transitions */
      --enable-animations: 1;     /* Set to 0 to skip CSS animations */
      --enable-shadows: 1;        /* Set to 0 to reduce box-shadows */
  ```
  Sweep result: no `var(--enable-transitions)`, `var(--enable-animations)`, `var(--enable-shadows)`, `var(--bg-opacity)` in any CSS file; no `setProperty` for them in any JS file.
- **Reproduction / verification:** `Select-String -Path ui\web_new_v2\css\*.css,ui\web_new_v2\css\components\*.css,ui\MACos_ui\*.css -Pattern "var\(--enable-|var\(--bg-opacity"` → 0 matches.
- **Suggested fix:** Delete the four unused declarations, or wire them into the animation/shadow rules and into the JS performance toggle.
- **Fix side effects:** None if deleted. If wired, the "low" profile would suddenly start suppressing transitions — a visible behaviour change that must be coordinated with `js/efficiency.js` (WN-30).
- **Discovered by:** A

---

#### F-WN-33-5  [P3] — `--font-display` names a font (`Plus Jakarta Sans`) that is remote and loaded only on demand, so heading rendering depends on whether the font picker was ever opened

- **File:** `ui/web_new_v2/css/tokens.css:100` (also `ui/web_new_v2/css/fonts.css:5-12`, `ui/web_new_v2/js/boot.js:19-36`, `ui/web_new_v2/js/settings.js:605-611`)
- **Confirmed:** yes
- **Description:** The display-font token is `--font-display: 'Sora', 'Plus Jakarta Sans', system-ui, -apple-system, sans-serif;`. `Sora` is self-hosted (`css/fonts.css:83-98`). `Plus Jakarta Sans` is **not** bundled — it is one of the five remote families fetched from `https://fonts.googleapis.com` by `boot.js:20-34`, and that fetch is lazy: it only runs when the font picker is rendered (`settings.js:609` `window.NeDotifyEnsurePickerFonts()`). `fonts.css` explicitly documents the opposite contract (*"no font CDN is contacted at startup"*, `fonts.css:9-12`) and `boot.js:7-8` asserts *"the UI renders correctly with no network at all"* — which is true for the two bundled families but not for the token stack that names a remote one.
- **Cause:** A bundled-family token stack was given a remote fallback entry, so the fallback for codepoints the bundled face lacks (all Cyrillic — see the "KNOWN GAP" note at `fonts.css:26-34`) is decided by whether a network request happened to succeed earlier in the session.
- **Trigger conditions:** Any session that has never opened Settings → Appearance → Fonts (no remote fetch ⇒ `Plus Jakarta Sans` unavailable) versus a session that has (fetch succeeded ⇒ `Plus Jakarta Sans` used for Cyrillic headings).
- **User impact:** Cyrillic headings render in `system-ui` on a fresh start and in `Plus Jakarta Sans` after the font picker has been opened and the CDN answered — an inconsistent typeface for the same UI, dependent on network availability and on user history. `fonts.css`'s stated offline-rendering guarantee does not hold for the token that names it.
- **Evidence:**
  `ui/web_new_v2/css/tokens.css:100`
  ```css
  --font-display: 'Sora', 'Plus Jakarta Sans', system-ui, -apple-system, sans-serif;
  ```
  `ui/web_new_v2/css/fonts.css:9-12`
  ```
   WHY: a desktop app has to render identically with the network unplugged.
   The remote <link> made the appearance depend on DNS, a proxy or a firewall,
  ```
  `ui/web_new_v2/js/boot.js:20-34`
  ```js
  var PICKER_FONT_HREF = 'https://fonts.googleapis.com/css2'
      + '?family=Inter:wght@300;400;500;600;700;800'
      ...
      + '&family=Plus+Jakarta+Sans:wght@400;500;600;700;800'
  ```
  `ui/web_new_v2/js/settings.js:605-611` — the fetch is triggered only from `renderFontCards()`.
- **Reproduction / verification:** Fresh profile, launch the app, inspect a Cyrillic heading (`#home-greeting`): the computed font-family lists `Plus Jakarta Sans` but the face is not loaded. Then open Settings → Appearance → Fonts, wait for the CDN request, and re-inspect: the face is now loaded and the same heading changes typeface.
- **Suggested fix:** Drop `'Plus Jakarta Sans'` from `--font-display` (leaving `'Sora', system-ui, -apple-system, sans-serif`) so the token stack contains only bundled/system faces, or bundle the family.
- **Fix side effects:** Cyrillic headings would permanently fall back to `system-ui`/`Segoe UI` instead of occasionally `Plus Jakarta Sans`; that is the same visual result as today's cold start, so the change makes behaviour deterministic rather than different.
- **Discovered by:** A (the lazy loader is **WN-30**; the token stack is WN-33)

---

#### F-WN-33-6  [P3] — The 17 `assets/theme-previews/*.png` files are shipped but never referenced at runtime, and the map that references them points 5 themes at the wrong image

- **File:** `ui/web_new_v2/js/settings-view.js:4-14`, `ui/web_new_v2/js/appearance-assets.js:29`, `:46-50`; assets under `ui/web_new_v2/assets/theme-previews/`
- **Confirmed:** yes
- **Description:** The theme cards in Settings are rendered with `themePreviewPath(t.id)` (`settings.js:579`). `themePreviewPath` (`settings-view.js:12-14`) is `window.NeDotifyAssets?.themePreviewPath(id) || (THEME_IMAGES[id] ? 'assets/theme-previews/<X>.png' : '')`. `NeDotifyAssets` is always present (`js/appearance-assets.js:46-50`, loaded at `index.html:12`), and it returns `assets/backgrounds/photo-<id>.jpg` for all 22 preset themes — so the `THEME_IMAGES` branch is **never taken** and all 17 PNGs (313 370 bytes) are dead weight shipped in the installer (`setup_pyinstaller.spec:27` bundles the whole `ui/web_new_v2` tree). The dead map is also internally wrong: `dracula→'06_Violet'`, `nord→'13_Slate'`, `rose→'07_Blossom'`, `emerald→'05_Mint'`, `amber→'10_Sand'` — five themes pointed at another theme's preview.
- **Cause:** A second preview-resolution path was left in place after `appearance-assets.js` took over; nothing removed the now-dead map or the PNGs.
- **Trigger conditions:** Always (the assets are shipped and never requested).
- **User impact:** ~306 KB (313 370 bytes) of dead assets in the installer. No runtime breakage — but if `NeDotifyAssets` ever fails to load (CSP/parse error), the picker falls back to the PNG map and 5 of 22 themes would show the wrong picture.
- **Evidence:**
  `ui/web_new_v2/js/settings-view.js:4-14`
  ```js
  const THEME_IMAGES = {
      dark:'01_Dark', amoled:'02_AMOLED', ... 
      dracula:'06_Violet', nord:'13_Slate', rose:'07_Blossom', emerald:'05_Mint', amber:'10_Sand'
  };
  export function themePreviewPath(id) {
      return window.NeDotifyAssets?.themePreviewPath(id) || (THEME_IMAGES[id] ? `assets/theme-previews/${THEME_IMAGES[id]}.png` : '');
  }
  ```
  `ui/web_new_v2/js/appearance-assets.js:29`, `:46-50`
  ```js
  const localPath = id => `assets/backgrounds/${id}.jpg`;
  ...
  themePreviewPath: id => themes[id] ? localPath(`photo-${themes[id]}`) : '',
  ```
  Asset listing: `ui/web_new_v2/assets/theme-previews/` contains exactly 17 PNGs (`01_Dark.png` … `17_Ocean.png`), total ≈ 340 KB; the preset list has 22 themes, so 5 themes have no PNG of their own even in the fallback map.
- **Reproduction / verification:** `Select-String -Path ui\web_new_v2\**\*.js,ui\web_new_v2\index.html -Pattern "theme-previews"` → only `settings-view.js:13` (the dead branch). In DevTools, the `<img>` inside `.theme-preview` has `src="assets/backgrounds/photo-….jpg"`, never `assets/theme-previews/*.png`. No CSS file references `theme-previews` either.
- **Suggested fix:** Delete `THEME_IMAGES` and `assets/theme-previews/` (and stop shipping them), or keep the PNGs as the primary source and drop the `appearance-assets.js` override.
- **Fix side effects:** Theme cards would lose the curated per-theme PNG art in favour of the Unsplash photo currently shown; the photo mapping is duplicated across 6 themes (`blossom`/`sakura`/`rose` share one photo, `sand`/`amber` another, `dark`/`emerald` another, `amoled`/`lavender` another), which is itself a visible shortcoming of the current preview.
- **Discovered by:** A (JS ownership **WN-30**; the CSS/asset inventory fact is WN-33)

---

#### F-WN-33-7  [P3] — `css/styles.css` is stale in three ways and is the source of an incomplete tooling inventory

- **File:** `ui/web_new_v2/css/styles.css:4-15`, `:17-45`, `:52-69` (also `tools/bench/css_inventory.py:49-66`, `ui/web_new_v2/index.html:17-50`)
- **Confirmed:** yes
- **Description:** `styles.css` is not linked (correctly, and it says so at `:4-10`), but its content is now wrong in three ways: (a) `:33-39` states *"index.html does NOT link it, so in the shipped app it is currently dead"* about `components/visual-polish.css` — but `index.html:45` links it; (b) `:17-28` presents a 9-entry *"AUTHORITATIVE LOAD ORDER"* ending with *"9. css/themes.css theme overrides — MUST stay last"*, while `index.html` links **25** stylesheets and puts `themes.css` at position 9 of 25, with 16 more files after it; (c) the `@import` chain `:52-69` omits `components/onboarding.css`, `components/ui-style-picker.css` and all four `MACos_ui/*.css`. `tools/bench/css_inventory.py:51-62` derives its hard-coded `IMPORT_ORDER` from that chain, so the CSS inventory tool parses **10 of the 25** live stylesheets (plus the unlinked `styles.css` itself as entrypoint) — 15 live stylesheets are invisible to it, including every `*-refresh.css` override layer, which is precisely the layer where F-WN-33-1 and F-WN-33-2 live.
- **Cause:** The architecture note was written for an earlier 9-file layout and never refreshed as the pack grew.
- **Trigger conditions:** Always — the file is read by humans (and by `css_inventory.py`), never by the browser.
- **User impact:** None at runtime. The risk is navigational: a maintainer following the stated order ("themes.css MUST stay last", "visual-polish.css is dead") will make changes that have no effect or that break the cascade — the exact class of mistake that produced F-WN-33-1 and F-WN-33-2.
- **Evidence:**
  `ui/web_new_v2/css/styles.css:28` — `9. css/themes.css                  theme overrides — MUST stay last`
  `ui/web_new_v2/css/styles.css:34-35` — *"index.html does NOT link it, so in the shipped app it is currently dead."*
  `ui/web_new_v2/index.html:28` and `:45-50`
  ```html
  <link rel="stylesheet" href="css/themes.css?v=20260827_blur">
  ...
  <link rel="stylesheet" href="css/components/visual-polish.css?v=20261006_polish">
  <link rel="stylesheet" href="css/components/ui-style-picker.css?v=20261016_macos">
  <link rel="stylesheet" href="MACos_ui/tokens.css?v=20261016_macos">
  <link rel="stylesheet" href="MACos_ui/interface.css?v=20261016_macos">
  <link rel="stylesheet" href="MACos_ui/settings.css?v=20261016_appearance">
  <link rel="stylesheet" href="MACos_ui/library.css?v=20261017_library">
  ```
  `tools/bench/css_inventory.py:51-62`
  ```python
  IMPORT_ORDER = [
      "fonts.css",
      "tokens.css",
      "components/base.css",
      "components/player-bar.css",
      "components/player-view.css",
      "components/lyrics.css",
      "components/home-view.css",
      "components/track-table.css",
      "themes.css",
      "components/visual-polish.css",
  ]
  ```
  — 10 entries; `onboarding.css`, `ui-style-picker.css`, all 9 `*-refresh.css` / `feature-tools` / `smart-playlists` / `downloads-view` files and the 4 `MACos_ui` files are absent.
- **Reproduction / verification:** `Select-String -Path ui\web_new_v2\index.html -Pattern 'rel="stylesheet"'` → 25 links; compare with `styles.css:20-28` (9 entries) and with `css_inventory.py:51-66`.
- **Suggested fix:** Regenerate the note from `index.html` (or make it machine-generated), and extend `css_inventory.py`'s `IMPORT_ORDER` to the real 25-entry list.
- **Fix side effects:** None at runtime; `css_inventory.py` output numbers will change (it will start counting the 6 previously-invisible stylesheets), which may invalidate stored baselines under `tools/bench/results/`.
- **Discovered by:** A

---

#### F-WN-33-8  [P3] — `MACos_ui/library.css` escapes its own pack root with `../assets/backgrounds/…`, a path the pack's own route is forbidden to serve

- **File:** `ui/MACos_ui/library.css:60` (also `ui/MACos_ui/interface.css:11`, `ui/MACos_ui/library.css:64`; `core/ui_assets.py:8-22`)
- **Confirmed:** yes (resolvable today, but only by accident of the mount layout)
- **Description:** `MACos_ui/library.css:60` references `url("../assets/backgrounds/photo-1519681393784-d120267933ba.jpg")`. On disk that path does not exist — `ui/` contains only `MACos_ui/`, `web_new_v2/`, `__init__.py`, `__pycache__/`, so `ui/assets/backgrounds/` is not a thing. The reference only resolves because the pack is mounted at the HTTP path `/MACos_ui/` (so `..` → `/`), while the server's document root is `ui/web_new_v2` — i.e. it escapes the pack and lands in the *new* pack's asset tree. `core/ui_assets.py:12` explicitly refuses to serve anything outside the pack (`if not target.is_relative_to(root) … return bottle.HTTPError(404, 'Asset not found')`), so the pack's own route can never satisfy it; it works only because the app's catch-all (`webview/http.py:122-130`, root = `ui/web_new_v2`) picks it up instead.
- **Cause:** The legacy pack was authored to sit next to `assets/` but is mounted one level deeper at runtime; the relative path was written against the on-disk layout and happens to be correct only for the HTTP layout.
- **Trigger conditions:** Always in the current build. It breaks if the pack is ever served from a different mount prefix, if `install_macos_assets` is changed to serve the pack under a nested path, or if the pack is opened directly from disk (e.g. a design preview).
- **User impact:** No current breakage — the JPEG resolves to `http://127.0.0.1:<port>/assets/backgrounds/photo-1519681393784-d120267933ba.jpg`, which exists. The risk is silent: if the mount changes, the library background simply stops rendering with no error surfaced to the user. Additionally `MACos_ui/interface.css:11` loads `assets/atmosphere-dusk.png`, a **1.42 MB PNG**, as the full-screen macOS wallpaper — the largest single asset in the UI and an easy win to convert to a JPEG/WebP.
- **Evidence:**
  `ui/MACos_ui/library.css:60`
  ```css
  background: linear-gradient(#141d3420,#19213b10),url("../assets/backgrounds/photo-1519681393784-d120267933ba.jpg") center 53%/cover;
  ```
  `core/ui_assets.py:10-14`
  ```python
  def macos_asset(filepath):
      target = (root / filepath).resolve()
      if not target.is_relative_to(root) or target.suffix not in {'.css', '.png', '.svg', '.woff2'}:
          return bottle.HTTPError(404, 'Asset not found')
  ```
  On-disk listing of `ui/`: `MACos_ui`, `web_new_v2`, `__pycache__`, `__init__.py` — no `ui/assets/`.
  `ui/MACos_ui/interface.css:11`
  ```css
  background-image: linear-gradient(#0a0f141a,#0a0f141a),url("assets/atmosphere-dusk.png");
  ```
  File size: `ui/MACos_ui/assets/atmosphere-dusk.png` = 1 424 752 bytes.
- **Reproduction / verification:** Resolve the URL manually: the stylesheet is served from `http://127.0.0.1:<port>/MACos_ui/library.css`, so `../assets/backgrounds/photo-1519681393784-d120267933ba.jpg` → `http://127.0.0.1:<port>/assets/backgrounds/photo-1519681393784-d120267933ba.jpg` → served from `ui/web_new_v2/assets/backgrounds/…` (exists). On disk, `Test-Path ui/assets/backgrounds/photo-1519681393784-d120267933ba.jpg` → `False`.
- **Suggested fix:** Give the pack its own copy of the asset (`ui/MACos_ui/assets/…`) so the `url()` stays inside the pack root, or reference the new pack's asset with an explicit absolute path that matches the mount (`/assets/backgrounds/…`), and convert `atmosphere-dusk.png` to a compressed JPEG/WebP.
- **Fix side effects:** Copying the JPEG into the pack adds ~360 KB to the installer; converting the PNG to JPEG changes the wallpaper's banding/quality and its ~1.4 MB → ~150 KB size.
- **Discovered by:** A

---

#### F-WN-33-9  [P3] — A third, divergent copy of the theme inventory exists in `js/settings.js` and is dead code

- **File:** `ui/web_new_v2/js/settings.js:35-46` (versus `js/settings.js:492-515` and `ui/web_new_v2/css/themes.css:29-422`)
- **Confirmed:** yes
- **Description:** `settings.js` contains two module-level theme lists. `PRESET_THEMES` (`:492-515`, 22 entries) is the live one used by `renderThemePresets()`. `THEMES` (`:35-46`, 10 entries: `amoled, dark, midnight, emerald, sunset, ocean, lavender, rose, amber, slate`) is declared and **never read** — a sweep of `ui/web_new_v2/js/**` finds no reference to it. Its colour tuples are in a different order from `PRESET_THEMES` (e.g. `THEMES.dark = ['#ffffff','#121212']` vs `PRESET_THEMES.dark = ['#121212','#ffffff','#1e1e1e']`), i.e. the two lists disagree about which slot is the background.
- **Cause:** The theme list was split/rewritten during the picker rework; the earlier array was left behind.
- **Trigger conditions:** Always (dead code, never executed).
- **User impact:** None at runtime. The risk is that the list drifts further: `themes.css` currently defines 23 theme blocks (22 presets + `light`), and a reader who trusts `THEMES` would conclude that only 10 themes exist — or would "fix" a theme and edit the wrong array.
- **Evidence:**
  `ui/web_new_v2/js/settings.js:35-46`
  ```js
  const THEMES = [
      { id: 'amoled', name: 'AMOLED', colors: ['#ffffff', '#000000'] },
      { id: 'dark', name: 'Dark', colors: ['#ffffff', '#121212'] },
      ...
      { id: 'slate', name: 'Slate', colors: ['#94a3b8', '#0f172a'] }
  ];
  ```
  `ui/web_new_v2/js/settings.js:492-494`
  ```js
  const PRESET_THEMES = [
      { id: 'dark', name: 'Dark', colors: ['#121212', '#ffffff', '#1e1e1e'] },
      { id: 'amoled', name: 'AMOLED', colors: ['#000000', '#ffffff', '#27272a'] },
  ```
  Reference sweep: `Select-String -Path ui\web_new_v2\js\*.js -Pattern "\bTHEMES\b"` → `settings.js:35` (the declaration) is the only hit in that file; the other hits are `appearance-assets.js:5` and `onboarding.js:5` (different constants).
- **Reproduction / verification:** `Select-String -Path ui\web_new_v2\js\settings.js -Pattern "THEMES"` → only lines 35 and 492 (`PRESET_THEMES`); no `THEMES.` / `THEMES[` usage.
- **Suggested fix:** Delete `settings.js:35-46` (WN-30 owns the file). Optionally add a test that asserts every id in `PRESET_THEMES` has a matching `:root[data-theme="<id>"]` rule in `themes.css`, so a future theme cannot be shipped without CSS.
- **Fix side effects:** None at runtime.
- **Discovered by:** A (JS ownership **WN-30**; reported here because the divergence is against the CSS theme catalogue)

---

### 3. Clean areas

- **Theme completeness — every picker theme has CSS.** `css/themes.css` defines 24 palette blocks: the bare `:root` (`:29-53`) plus 23 named ones — `amoled` (`:56`), `dark` (`:68`), `midnight` (`:86`), `emerald` (`:98`), `sunset` (`:110`), `ocean` (`:122`), `lavender` (`:134`), `rose` (`:146`), `amber` (`:158`), `slate` (`:170`), `neutral` (`:182`), `crimson` (`:194`), `dracula` (`:206`), `nord` (`:218`), `sky` (`:230`), `mint` (`:242`), `violet` (`:254`), `blossom` (`:266`), `sakura` (`:278`), `terminal` (`:290`), `sand` (`:302`), `aqua` (`:314`), `light` (`:390`). The live picker list `PRESET_THEMES` (`js/settings.js:492-515`) contains 22 ids — **all 22 have a matching `:root[data-theme="…"]` rule**; `light` is the extra one and is the mode-theme used by `applyThemeMode` (`js/settings.js:1842`). There is **no theme in the picker without CSS**, and no CSS theme missing from the picker other than `light` (which is intentionally not a preset). The onboarding picker (`js/onboarding.js:5-10`: `dark, midnight, mint, light`) also only offers themes that exist in CSS.
- **Every theme preview path resolves to a file that exists.** All 22 `PRESET_THEMES` ids map through `js/appearance-assets.js:5-28` to `assets/backgrounds/photo-<id>.jpg`, and all 22 target files exist in `ui/web_new_v2/assets/backgrounds/`. (The separate 17 PNGs under `assets/theme-previews/` are dead — see F-WN-33-6.)
- **No undefined custom property without a fallback.** Every `var(--x)` in `ui/web_new_v2/css/**` that has no definition in `tokens.css` / `themes.css` carries an explicit fallback, so nothing silently resolves to the initial value: `--app-bg` (`base.css:255`), `--aura-orb-1/2` (`base.css:4068/4077/4087`; also set at runtime by `js/player.js:1727-1728`), `--border-color` (`feature-tools.css:3`), `--lib-collection-count` (`library-refresh.css:64`, `MACos_ui/library.css:76`), `--orbit-glow-1/-border/-opacity/-scale` (`player-bar.css:74-76`, `player-view.css:83-85`), `--player-progress-color` (`player-bar.css:361,366`), `--primary-hover` (`base.css:2239`), `--search-header-height` (`base.css:4234`), `--value-percent` (`base.css:1399`, `settings-refresh.css:172`; set inline by JS). The `tokens.css:50` `var(--border-glow, rgba(var(--primary-rgb), 0.15))` fallback is deliberate and documented at `tokens.css:25-30`.
- **`ui/MACos_ui/**` is NOT dead code.** It is `<link>`ed at `index.html:47-50`, and it *is* reachable at runtime: `main.py:424-425` calls `core/ui_assets.py::install_macos_assets(app, base_dir)`, which registers one exact Bottle route per pack file under `/MACos_ui/…`. The pack's relative `<link href="MACos_ui/tokens.css">` resolves correctly because the pywebview window is served from the local HTTP server (`main.py:350` passes a filesystem path, which pywebview 5.4 turns into `http://127.0.0.1:<port>/index.html` via `webview/http.py:86-155` and `webview/window.py:548-555`), so the relative URL becomes `/MACos_ui/tokens.css` and hits the exact route. Bottle checks **static** routes before dynamic ones (`bottle.py:465-479` with `Router(strict=False)` at `bottle.py:318`/`656`), so the pack's exact routes do take precedence over pywebview's `/<file:path>` catch-all — the comment at `core/ui_assets.py:16-18` is accurate. `tests/test_macos_ui.py:17-44` pins this and passes. The pack is therefore **shipped and live**, not bloat — it is a second, macOS-flavoured presentation layer (`html[data-ui-style="macos"]` selectors) layered on top of `web_new_v2`, selected by `js/ui-style.js` (WN-30).
- **The macOS layer is properly namespaced.** Every selector in `MACos_ui/interface.css`, `settings.css`, `library.css` is prefixed with `html[data-ui-style="macos"]` (specificity ≥ `(0,2,0)`), and `MACos_ui/tokens.css:4` / `:68` scope the palette overrides to `:root[data-ui-style="macos"]`. Consequently the pack only wins inside macOS mode; outside it, `web_new_v2` is unaffected. `MACos_ui/tokens.css:30-44` uses `!important` deliberately (documented at `:1-3`) to mask inline custom colours.
- **`@font-face` sources resolve.** All six `url('../assets/fonts/…woff2')` paths in `css/fonts.css:48,57,69,78,88,97` resolve from `ui/web_new_v2/css/` to `ui/web_new_v2/assets/fonts/`, and all six files exist (`dmsans-latin-400-normal`, `dmsans-latin-400-italic`, `dmsans-latin-ext-400-normal`, `dmsans-latin-ext-400-italic`, `sora-latin-600-normal`, `sora-latin-ext-600-normal`). `fonts.css` **is** linked (`index.html:17`, first in the head, before every rule that asks for a family). The family names `'DM Sans'` and `'Sora'` match `--font-body` / `--font-display` (`tokens.css:100-101`).
- **`prefers-reduced-motion` is honoured.** 12 blocks across `base.css:1733,3372,4252`, `home-refresh.css:244`, `library-refresh.css:188`, `lyrics.css:464`, `onboarding.css:129`, `profile-refresh.css:100`, `search-refresh.css:119`, `settings-refresh.css:108`, `visual-polish.css:204`, `MACos_ui/interface.css:288`. There is **no** `prefers-color-scheme` query in any stylesheet — this is by design: the system light/dark preference is resolved in JS (`js/settings.js:1832-1846` `applyThemeMode`, `js/ui-style.js:4,71,284`), because the app owns the palette mapping (`data-theme` → `[data-theme=…]` blocks), not the browser.
- **`SOURCES.json` is fully consistent.** 27 entries ↔ 27 JPEGs on disk, no extras, no omissions, and **all 27 SHA-256 digests re-verified as matching** the shipped bytes. All 27 are referenced by `js/appearance-assets.js` (`photos` set / `themes` map).
- **`data-theme` is only ever set on `<html>`.** Every write goes through `document.documentElement.setAttribute('data-theme', …)` (`js/settings.js:590,726,1842,1844`, `js/main.js:212`); no element ever carries a `data-theme` attribute, so the bare `[data-theme="dark"]` selector in `themes.css:68` is equivalent to the `:root[...]` one and cannot create a scoped sub-theme.
- **Load order is otherwise sound.** `index.html:17-50` is `fonts → tokens → base → components → themes → *-refresh layer → visual-polish → ui-style-picker → MACos_ui`, i.e. the override layer comes after the layer it overrides, and the legacy pack is last. The only two order-dependent defects found are F-WN-33-1 and F-WN-33-2.

### 4. Coverage gaps

- **No browser was run.** I did not launch the app (per the brief) and there is no headless WebView2/CDP harness in this environment that could evaluate the cascade empirically. All cascade conclusions are derived from the CSS cascade rules applied to the *actual* `<link>` order read out of `index.html:17-50`; each is reproducible in DevTools with the one-liner given in the finding. The `tools/visual_guard` harness (`tools/visual_guard/capture.py`, `fixtures.py`) would be the way to confirm F-WN-33-1/F-WN-33-2 pixel-wise; I did not run it because it drives the real app.
- **I did not verify the rendering of the 22 non-`dark` themes.** Their CSS blocks are present and unshadowed, so they should apply as written; but only `dark` has a conflicting later declaration, so the other 21 were checked structurally (selector + property presence), not visually.
- **`base.css` (129 KB) was not read end-to-end.** It was swept programmatically for every `var()` usage, every custom-property declaration, every `url()`, every media context and every selector collision, and read in ~35 targeted ranges around the rules that participate in conflicts; but the ~4400 lines were not individually eyeballed, so an issue that is purely visual (e.g. a contradictory pair of rules on the same element that neither redefines a shared property) could have been missed.
- **The `MACos_ui` pack was reviewed structurally, not rendered.** Its rules were parsed, scoped-checked and asset-path-checked; whether the resulting macOS layout is visually correct was not assessed.
- **The visual-regression and bench baselines** under `tools/bench/results/` and `tools/visual_guard/reports/` were not re-run, so I cannot say whether F-WN-33-1 is a recent regression or has been present since the "home refresh" work landed.
- **Ownership boundary.** Where a defect's root cause is in JS (`ui-style.js`, `settings.js`, `settings-view.js`, `appearance-assets.js`), I recorded only the CSS/asset-side facts and named the owning area (WN-30). I did not audit the JS logic itself.
