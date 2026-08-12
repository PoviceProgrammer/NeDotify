# Worker Task for Milestone 4 (Animations & Audio) - Gen 2

Implement the Mock API layer, HTML5 Audio synchronization, and Framer Motion visual polish in the Aure Music v2 frontend application.

## Detailed Requirements

1. **Mock API (`src/api/mockApi.ts`)**:
   - Return track metadata asynchronously.
   - Implement `getTracks(options?: { delayMs?: number })` and `getTrackDetails(id: string, options?: { delayMs?: number })` with authentic server delay simulation (default to 100ms).
   - Ensure the track structures follow the contract: `{ id, title, artist, album, duration, coverUrl, audioUrl }`.

2. **Zustand Player Store (`src/store/playerStore.ts` and `src/store/usePlayerStore.ts`)**:
   - Integrate native HTML5 Audio element inside `usePlayerStore` Zustand store logic.
   - We recommend using a module-level `HTMLAudioElement` singleton initialized inside `playerStore.ts` (with SSR and JSDOM check: `typeof window !== 'undefined' && typeof window.Audio !== 'undefined'`).
   - Sync Zustand state `isPlaying`, `currentTime`, `duration`, `volume`, `playlist` (the dynamic queue), and `currentTrack` with the Audio element.
   - Actions to implement/refactor:
     - `setPlaying(val)`: Play or pause the audio.
     - `setVolume(vol)`: Scale and set the audio volume (0-1).
     - `setCurrentTime(time)`: Set the audio `currentTime`. Use delta thresholds (e.g. > 1.2s) to prevent recursive feedback loop ticks.
     - `setPlaylist(tracks)`: Update the queue.
     - `nextTrack()` and `prevTrack()`: Cycle through the playlist (dynamic queue) using modulo arithmetic.
   - Add event listeners on the audio element:
     - `timeupdate`: Update store's `currentTime` if delta > 0.8s.
     - `durationchange`: Update store's `duration`.
     - `ended`: Automatically call `nextTrack()`.
     - `error`: Reset `isPlaying` to false.

3. **UI and Framer Motion Polish**:
   - **Album Cover in `src/components/MainPanel.tsx`**:
     - Wrap cover image in `AnimatePresence` with `mode="wait"`.
     - Use a keyframed entry transition (`animate={{ opacity: [0, 0.5, 1], scale: [0.9, 1.02, 1], rotate: 0 }}`) and a custom exit transition.
     - Add dynamic hover scaling and shadows.
   - **Controls & Buttons in `src/components/ControlsBar.tsx`**:
     - Replace text buttons (Prev, Play, Next) with SVG icons + text.
     - Apply micro-interactions: `whileHover={{ scale: 1.08 }}` and `whileTap={{ scale: 0.92 }}`.
     - Add interactive volume mute button with changing speaker icons depending on volume (0%, 1-49%, 50%+) and click-to-mute.
   - **Sidebar Theme Swatches in `src/components/Sidebar.tsx`**:
     - Convert theme swatch buttons to `motion.button` with hover/tap scaling.
     - Use Framer Motion's `layoutId="active-theme-bg"` on a background capsule for smooth transitions between the active theme.
   - **Progress Bar in `src/components/ControlsBar.tsx`**:
     - Replace the native unstyled range slider with a custom styled bar: an animated background track, an animated filled progress track, and an animated thumb handle.
     - Keep the native `<input type="range">` on top but set `opacity: 0` so hover/drag events and keyboard arrows work natively.
     - Track dragging state with a React state `isDragging` so that dragging update transitions are instantaneous (`duration: 0`) and natural playback tick updates are smoothed (`duration: 0.15`, linear).

4. **Testing Infrastructure Setup (`src/tests/setup.ts`)**:
   - Mock the global `Audio` constructor in Vitest setup to avoid JSDOM errors, mimicking listeners (`addEventListener`, `removeEventListener`), state, and methods (`play()`, `pause()`, `load()`).

5. **Compilation, Linting, and Verification**:
   - Run compilation and linting to ensure 0 errors/warnings.
   - Run tests using `npm test` or `npx vitest run` in the `aure-music-v2` directory to verify all tests pass.
