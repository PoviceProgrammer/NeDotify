# Handoff Report - Milestone 4 (Animations & Audio) Exploration

## 1. Observation
We examined the current layout, state management, API simulations, and testing parameters across the following files:

1. **Mock API Layer (`aure-music-v2/src/api/mockApi.ts`)**:
   - Lines 1-9: `Track` interface shape configuration.
   - Lines 41-48:
     ```typescript
     export async function getTracks(): Promise<Track[]> {
       return new Promise((resolve) => {
         // Simulate real async API response
         setTimeout(() => {
           resolve([...mockTracks]);
         }, 10);
       });
     }
     ```
2. **Player Zustand Store (`aure-music-v2/src/store/playerStore.ts`)**:
   - Lines 25-53: Static track list `STATIC_PLAYLIST`.
   - Lines 74-92 (`nextTrack`) and Lines 93-111 (`prevTrack`): Cycle through `STATIC_PLAYLIST`. For example:
     ```typescript
     const idx = STATIC_PLAYLIST.findIndex(t => t.id === currentTrack.id);
     ```
3. **Vitest Config (`aure-music-v2/vite.config.ts`)**:
   - Lines 34-38:
     ```typescript
     test: {
       globals: true,
       environment: 'jsdom',
       setupFiles: './src/tests/setup.ts',
     },
     ```
4. **Package.json scripts (`aure-music-v2/package.json`)**:
   - Line 10: `"test": "vitest run"`

---

## 2. Logic Chain
1. **Dynamic Playback Queue**:
   - *Observation*: The store cycles tracks based on `STATIC_PLAYLIST` (e.g., lines 80, 99).
   - *Reasoning*: If the UI loads dynamic track lists via mock API, next/prev actions will fall back onto hardcoded static tracks.
   - *Conclusion*: A dynamic `queue` state and matching state management actions (`setQueue`, `loadTracksFromApi`) must be introduced to the Zustand player store, and `nextTrack`/`prevTrack` must cycle on the store's dynamic queue.
2. **Mock API Enrichment**:
   - *Observation*: `mockApi.ts` only provides `getTracks` (lines 41-48). Test files assert on simulated delays, schema structures, and failure handling.
   - *Reasoning*: To support direct queries or single-track details in later features, the mock API layer needs to mimic a real database engine.
   - *Conclusion*: Extend the API with `getTrackDetails(id: string)` and parameters to configure delay and force promise rejection (failure modes).
3. **JSDOM Audio Test Executability**:
   - *Observation*: `vite.config.ts` specifies a `jsdom` testing environment (line 36).
   - *Reasoning*: HTML5 audio elements are stubbed inside JSDOM and do not support active media methods (`play`, `pause`, `load`). Synchronizing Zustand actions with a real audio element will crash the test suite under JSDOM.
   - *Conclusion*: The test setup file (`setup.ts`) must globally mock `HTMLMediaElement.prototype.play`, `pause`, and `load` before audio sync is implemented.

---

## 3. Caveats
- **Audio Element in Testing**: The proposed singleton audio engine is not active during tests. We assumed standard browser media element behavior when mocking HTMLMediaElement for tests.
- **Tauri Native Audio**: We assumed HTML5 `Audio` is sufficient for Tauri execution on target platforms without native Rust audio bindings.

---

## 4. Conclusion
We recommend:
1. Enhancing `mockApi.ts` with `getTrackDetails` and configurable network delays/errors.
2. Adding `queue` and actions (`setQueue`, `loadTracksFromApi`) to Zustand, updating `nextTrack` and `prevTrack` to cycle on it.
3. Implementing an global `AudioEngine` singleton that subscribes to Zustand updates and updates a native HTML5 audio object, protecting against recursive loop triggers.
4. Adding HTMLMediaElement mocks to `src/tests/setup.ts` to prevent Vitest test suites from failing in JSDOM.

---

## 5. Verification Method
- **Implementation Inspection**:
  - Verify that `mockApi.ts` exports `getTracks` and `getTrackDetails` as async Promises.
  - Verify that `playerStore.ts` contains `queue: Track[]` and dynamic actions, and cycles on `state.queue`.
- **Unit and Integration Verification**:
  - Navigate to `/aure-music-v2` and run `npm test` or `npx vitest run`.
  - Invalidation condition: If the tests fail, ensure `setup.ts` correctly mocks `play()` and other media element functions.
