# Scope: E2E Testing Suite for Aure Music v2

## Architecture
- Target project: `aure-music-v2`
- Test Runner: Vitest
- Test Library: React Testing Library + Happy DOM / JSDOM
- Interfaces under test:
  1. `usePlayerStore` (Zustand store handling theme, transparency, playback status, current track, volume, and playback time).
  2. `mockApi` (Async mock API layer returning track metadata).
  3. `AurePlayer` UI component and subcomponents (Sidebar, Main Content with cover art, Controls Bar, theme options).
  4. Styles (Tailwind theme configurations, Glassmorphism backdrop-blur, custom scrollbars, window padding).

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| 1 | Env Setup & Stubs | Initialize `aure-music-v2` directory, create package.json, vitest config, and create stub interface files for components, stores, and API layer. | None | DONE |
| 2 | Test Case implementation | Write all 77+ E2E test cases across Tiers 1-4 in Vitest, referencing the stubs. | M1 | DONE |
| 3 | Validation & Publish | Verify the tests compile and run, then publish `TEST_INFRA.md` and `TEST_READY.md` to the project root. | M2 | DONE |

## Interface Contracts
### Player Store (Zustand)
- `isTransparencyEnabled`: boolean
- `setTransparencyEnabled`: (val: boolean) => void
- `theme`: ThemeName
- `setTheme`: (theme: ThemeName) => void
- `currentTrack`: Track | null
- `isPlaying`: boolean
- `volume`: number (0-100)
- `currentTime`: number
- `duration`: number
- `setPlaying`: (val: boolean) => void
- `setCurrentTrack`: (track: Track) => void
- `setVolume`: (vol: number) => void
- `setCurrentTime`: (time: number) => void
- `nextTrack`: () => void
- `prevTrack`: () => void

### Mock API (src/api/mockApi.ts)
- `getTracks()`: Promise<Track[]>
- `Track` shape: `{ id: string, title: string, artist: string, album: string, duration: number, coverUrl: string, audioUrl: string }`

### UI Elements Classes / Test IDs
- Sidebar Navigation: `data-testid="sidebar"`
- Play/Pause Button: `data-testid="play-pause-button"`
- Next Track Button: `data-testid="next-button"`
- Previous Track Button: `data-testid="prev-button"`
- Cover Art Image: `data-testid="cover-art"`
- Volume Slider: `data-testid="volume-slider"`
- Progress Slider: `data-testid="progress-slider"`
- Theme Swatches / Buttons: `data-testid="theme-swatch-[theme-name]"`
- Transparent Toggle Checkbox/Button: `data-testid="transparency-toggle"`
