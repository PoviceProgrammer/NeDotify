# Scope: Milestone 4: Animations & Audio

## Architecture
- Mock API Layer (`src/api/mockApi.ts`):
  - Fetches mock JSON tracklists asynchronously, simulating server delay.
  - Return track metadata (title, artist, album, duration, coverUrl, audioUrl).
- Audio Playback Engine:
  - Connect Zustand state to a native HTMLAudioElement instance.
  - Synchronize store state (`isPlaying`, `currentTime`, `duration`, `volume`) to the audio element.
  - Ensure track changes, volume sliders, and progress scrubbing update the audio element immediately.
- Animations (Framer Motion):
  - Album Cover: Wrap the album cover image in `AnimatePresence` with smooth keyframed fade/scale transitions when the current track changes.
  - Buttons: Apply `whileHover={{ scale: 1.05 }}` and `whileTap={{ scale: 0.95 }}` to controls.
  - Progress Bar: Animate the filled progress track width smoothly.

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| 4.1 | Mock API Integration | Implement and connect the mock API layer to load tracks dynamically into the player queue | None | PLANNED |
| 4.2 | HTML5 Audio Sync | Bind Zustand store state and actions to an HTMLAudioElement instance for real audio playback | 4.1 | PLANNED |
| 4.3 | Framer Motion Polish | Add album cover transitions, button hover/tap animations, and smooth progress tracking | 4.2 | PLANNED |
| 4.4 | Unit & Integration Verification | Run unit and integration tests verifying playback, queue cycling, and animations | 4.3 | PLANNED |
