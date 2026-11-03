# Windows CSS audit remediation

Scope: `ui/web_new_v2/` and the desktop-only `ui/MACos_ui/` style pack. The
application and WebView were not launched.

## Findings

| Audit | Status | Evidence |
|---|---|---|
| AUD-403 selector ownership | No undeclared unconditional conflicts; reviewed scoped overrides are allowlisted | `base.css` no longer owns the shared `#player-bar` glass declaration. The sole normal `backdrop-filter` rule for that bar is in `home-refresh.css`; battery saver, no-backdrop, and unfocused states remain intentional overrides. A scan of `base.css` plus the current `*-refresh.css` files finds 219 exact `(selector, property)` pairs with different values across 122 selectors: 218 have a media/supports condition, one is a state selector, and none are unconditional conflicts. The duplicate `.context-menu-item:hover` declaration was deduplicated while preserving its effective `rgba(255,255,255,0.1)` value. `CSS_CONFLICT_ALLOWLIST.json` records the remaining exact variants and conditions; a regression test fails on a new or changed pair unless the manifest is reviewed. |
| AUD-404 duplicate token owners | Fixed for blur tokens and the audited `base.css` overlap | Blur scale and the 16px surface cap are defined in `tokens.css`; `base.css` no longer declares them. Performance presets also live in `tokens.css`. CSS wiring tests confirm the relevant blur tokens are absent from `base.css`. |
| AUD-406 blocking view styles | Fixed for the view packs | `index.html` retains 13 eager stylesheet links and 12 href-less stylesheet slots. `style-loader.js` activates Search, Library, Downloads, Smart Playlists, feature tools, Settings, Profile, style picker, and macOS view sheets on demand while slots retain authored cascade positions. A Node DOM harness executes the production loader and verifies no view pack loads at startup, Library loads only its pack, and macOS Library styles load after switching styles. |
| AUD-407 blur surfaces | Fixed for the large audited surfaces | `--blur-surface-cap` is 16px; `--blur-sm/md/lg/xl` clamp user-selected blur to that cap. The full-screen lyrics overlay now uses the capped token. macOS sidebar, player, Library, and Settings surfaces cap `--mac-panel-blur` at 16px. CSS/DOM tests inspect real rules against representative DOM elements and reject the old 20–40px literals. |
| AUD-408, AUD-444 | Fixed | Removed the `blur(8px)` filter from the full-screen `#particles-bg` canvas to avoid blurring the whole viewport; removed the unused `.particle` rule and its animation. The settings overlay keeps its authored no-backdrop/no-transition base state; `settings-refresh.css` owns the supported blur on the active settings surface. |

The custom wallpaper blur control (`theme.bg_blur`) now ranges from 0 to 16px.
Legacy stored values above 16 render as 16px in the settings control and the
background layer. Restoring this value does not write unrelated theme colors or
window opacity; the backend value is updated only when the user changes the
slider.

## CSS ownership map

| Layer | Owner | Loading |
|---|---|---|
| Raw palette | `css/themes.css` | Eager |
| Semantic, blur, focus, z-index, and performance tokens | `css/tokens.css` | Eager |
| Cross-view primitives and shared overlays | `css/components/base.css` | Eager |
| Player bar structure and controls | `css/components/player-bar.css` | Eager |
| Home surfaces and the normal player glass treatment | `css/components/home-refresh.css` | Eager, after theme palette |
| View-specific styles | `*-refresh.css`, `downloads-view.css`, `smart-playlists.css`, `feature-tools.css`, and `profile-refresh.css` | Deferred by the matching page |
| Settings style picker | `ui-style-picker.css` | Deferred with Settings |
| macOS tokens and interface | `ui/MACos_ui/tokens.css`, `interface.css` | Deferred until macOS style is selected |
| macOS Library/Settings details | `library.css`, `settings.css` | Deferred until that view is selected |
| Cross-view focus and reduced-motion overrides | `visual-polish.css` | Eager after themes |

`css/styles.css` remains a tooling index and is not loaded by the application.
Deferred links stay at their authored positions in `index.html`; the loader sets
their `href` in place so cascade order does not depend on network completion.

## Verification

Command:

```powershell
& ".venv_win\Scripts\python.exe" -m pytest tests/test_frontend_css_wiring.py -q
```

Result: **62 focused CSS wiring and declaration-guard checks passed**. The tests include a production-loader
Node DOM harness, stylesheet-slot order assertions, token owner checks, and
selector checks over a synthetic HTML DOM using the real linked CSS rules.
The settings UI suite additionally checks legacy `bg_blur=40` restoration and
verifies no unrelated setting writes occur.

The static declaration guard is green at **411 current / 411 baseline**, with
zero removed or changed declarations. The baseline is static source data only;
no pixel golden or animation runtime capture was regenerated.

## Remaining work

The source selectors outside this base/refresh comparison still use legacy
component and theme overrides. The manifest covers the audit's base/refresh
boundary, and future edits to that boundary must review any conflict drift.
