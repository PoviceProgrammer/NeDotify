# Project: AURA Music Linux UI Overhaul

## Architecture
- **Environment**: Linux (WebKitGTK 4.1 / Cairo / FreeType / Wayland)
- **Active Web UI**: `ui/web_new_v2/`
- **Backend**: Python 3 / Bottle HTTP Server (`main.py`, `core/settings.py`, `core/api.py`)
- **Remote Automation Bridge**: Bottle endpoints `/__aura_eval` and `/__aura_close`
- **Automated Capture Engine**: Native Wayland capture (`grim`) and WebKitGTK snapshot API

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Particles Container & Stacking | Elevate `#particles-bg` to z-index: 20 with `pointer-events: none`, remove destructive `filter: blur(8px)`, fix `inset: 0` | M1 | Survey |
| 2 | Particles Engine & Backend Settings | Synchronize `"particles_shape": "dot"`, prevent event listener leaks in `particles.js`, add Linux emoji fallbacks | M1 | Survey |
| 3 | Font Variable Propagation | Unify `--font-family`, `--font-body`, and `--font-display` in `tokens.css` and `settings.js` | M2 | Survey |
| 4 | Linux Fonts & Cyrillic Support | Add `Inter` with Cyrillic subset to Google Fonts, add native Linux font fallbacks (Ubuntu, Cantarell, Liberation Sans) | M2 | Survey |
| 5 | Font Settings & Active Cards | Fix `highlightActiveFontCard` matching in `settings.js`, fix backend default `"system"` -> `"default"` | M2 | Survey |
| 6 | Linux Text Antialiasing | Optimize FreeType/Cairo text rendering and subpixel smoothing in `base.css` | M2 | Survey |
| 7 | Player Header Span Preservation | Preserve `#pp-title` and `#pp-artist` DOM spans during track updates in `player.js` | M3 | Survey |
| 8 | Player Tab Layout & Alignment | Fix 2-column layout, left card `justify-content` and height overrun, wrap controls cleanly in `player-view.css` | M3 | Survey |
| 9 | Player Volume Controls | Provide volume slider on `#view-player` page | M3 | Survey |
| 10 | Waveform & Visualizer Resize | Recompute waveform and visualizer dimensions when `#view-player` becomes visible | M3 | Survey |
| 11 | Responsive Player Layout | Fix `@media (max-width: 900px)` targeting `.player-2col-layout` | M3 | Survey |
| 12 | Queue Handler Cleanup | Deduplicate `#pp-btn-queue` click handlers between `player.js` and `queue.js` | M3 | Survey |
| 13 | Automated Visual Testing Suite | Develop `tests/test_visual_ui.py` using `/__aura_eval` + `grim` | M4 | Survey |
| 14 | UI State Screenshot Capture | Automatically capture screenshots verifying particles, fonts, player tab, and settings | M4 | Survey |
| 15 | App Launch & Stability Check | Verify main application launches and runs locally without crashing | M4 | Survey |
| 16 | Independent Quality & Integrity Audit | Multi-reviewer, challenger, and forensic audit verification | M5 | Survey |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | UI Fix: Particles Background | `ui/web_new_v2/css/components/base.css`, `ui/web_new_v2/js/particles.js`, `core/settings.py`, `ui/web_new_v2/js/main.js` | None | DONE |
| M2 | UI Fix: Font System & Rendering | `ui/web_new_v2/css/tokens.css`, `ui/web_new_v2/css/components/base.css`, `ui/web_new_v2/index.html`, `ui/web_new_v2/js/settings.js`, `core/settings.py` | None | DONE |
| M3 | UI Fix: Player Tab Layout & Functionality | `ui/web_new_v2/css/components/player-view.css`, `ui/web_new_v2/css/components/player-bar.css`, `ui/web_new_v2/js/player.js`, `ui/web_new_v2/index.html`, `ui/web_new_v2/js/pages.js` | None | DONE |
| M4 | Automated Visual Testing & Screenshot Verification | `tests/test_visual_ui.py`, `screenshots/` | M1, M2, M3 | DONE |
| M5 | Final Verification & Forensic Audit | Full test execution, challenger tests, forensic integrity audit | M4 | DONE |

## Code Layout & Ownership Boundaries
- **M1 Worker**:
  - `ui/web_new_v2/css/components/base.css` (Particles container section: lines 1438-1449)
  - `ui/web_new_v2/js/particles.js`
  - `core/settings.py` (Particles section: line 203)
  - `ui/web_new_v2/js/main.js` (Particles sync: lines 203-206)
- **M2 Worker**:
  - `ui/web_new_v2/css/tokens.css`
  - `ui/web_new_v2/css/components/base.css` (Font antialiasing & hardcoded font classes)
  - `ui/web_new_v2/index.html` (Google Fonts link)
  - `ui/web_new_v2/js/settings.js` (FONTS_LIST, applyFontFamily, card matching)
  - `core/settings.py` (font_family default: line 165)
- **M3 Worker**:
  - `ui/web_new_v2/css/components/player-view.css`
  - `ui/web_new_v2/css/components/player-bar.css`
  - `ui/web_new_v2/js/player.js`
  - `ui/web_new_v2/index.html` (Player tab markup)
  - `ui/web_new_v2/js/pages.js`
- **M4 Worker**:
  - `tests/test_visual_ui.py`
  - `screenshots/*.png`
