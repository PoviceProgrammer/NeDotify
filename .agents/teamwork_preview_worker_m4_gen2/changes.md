# Changes - Milestone 4 (Animations & Audio)

The following modifications were made to the codebase in the `aure-music-v2` project:

## 1. Mock API Layer (`src/api/mockApi.ts`)
- Parameterized the `getTracks` function with `options?: { delayMs?: number }` to support custom server delays (defaulting to 100ms).
- Returns deep copies/clones of the mock track list to prevent shared state mutations.
- Implemented `getTrackDetails(id: string, options?: { delayMs?: number })` returning a single track metadata object after a simulated delay (defaulting to 100ms), or throwing an error if the track is not found.

## 2. Zustand Player Store (`src/store/playerStore.ts`)
- Initialized a module-level `HTMLAudioElement` singleton `audio` ensuring SSR/JSDOM safety via check (`typeof window !== 'undefined' && typeof window.Audio !== 'undefined'`).
- Integrated dynamic `playlist` array and `setPlaylist` action in `PlayerState`.
- Synced state properties `isPlaying`, `currentTime`, `duration`, and `volume` with the `audio` element.
- Added event listeners for `timeupdate` (syncing store's `currentTime` with a >0.8s delta threshold to prevent feedback loops), `durationchange`, `ended` (calling `nextTrack()`), and `error` (setting `isPlaying: false`).
- Implemented robust actions:
  - `setPlaying(val)`: Plays or pauses the audio singleton.
  - `setVolume(vol)`: Sets state volume (0-100) and scales it to set `audio.volume` (0-1).
  - `setCurrentTime(time)`: Sets state current time and checks against a delta >1.2s threshold before writing back to the `audio.currentTime` to prevent recursion loops.
  - `nextTrack()` and `prevTrack()`: Cycles queue (using the dynamic `playlist` array). Returns early if `currentTrack` is null or not found in the playlist, satisfying fallback and recovery tests.

## 3. Mock Audio Setup for Tests (`src/tests/setup.ts`)
- Implemented a complete `MockAudio` class mimicking the native `HTMLAudioElement`.
- Implemented listeners registry (`addEventListener`/`removeEventListener`), state variables (`src`, `volume`, `currentTime`, `duration`, `paused`), and playback controllers (`play()`, `pause()`, `load()`).
- Injected `MockAudio` as `globalThis.Audio` and `window.Audio`.
- Satisfied ESLint checking constraints (e.g. no empty `Function` types and proper type casts).

## 4. Album Cover Transitions (`src/components/MainPanel.tsx`)
- Wrapped the album cover in `AnimatePresence` with `mode="wait"`.
- Configured a keyframed entry transition (`animate={{ opacity: [0, 0.5, 1], scale: [0.9, 1.02, 1], rotate: 0 }}`) and a custom exit transition (`exit={{ opacity: 0, scale: 0.95, rotate: 2 }}`).
- Added responsive hover actions with scaling to `1.05` and custom box-shadow styling.

## 5. Controls and Progress Bar Polish (`src/components/ControlsBar.tsx`)
- Substituted static text buttons (Prev, Play, Next) with crisp inline SVG graphics.
- Bound hover/tap micro-interactions (`whileHover={{ scale: 1.08 }}`, `whileTap={{ scale: 0.92 }}`).
- Created an interactive click-to-mute button with changing volume icons depending on current volume (0%, 1-49%, 50%+).
- Replaced the unstyled native progress slider with a custom slider comprising an animated background track, an animated filled track, and an animated thumb handle.
- Set the native input range element opacity to `0` and laid it on top of the custom slider to preserve native keyboard accessibility and sliding actions.
- Introduced `isDragging` pointer state to disable transitions during active scrub drags, while keeping a `0.15s` linear transition for normal ticks.

## 6. Sidebar Theme Swatches (`src/components/Sidebar.tsx`)
- Converted theme selector swatches to `motion.button` with hover/tap scaling.
- Integrated Framer Motion's `layoutId="active-theme-bg"` on a background capsule `motion.div` to smoothly slide the active accent background container between different selected themes.
