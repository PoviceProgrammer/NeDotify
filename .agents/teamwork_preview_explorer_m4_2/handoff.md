# Handoff Report - Explorer 2 (Milestone 4: Animations & Audio)

## 1. Observation

Direct observations made during the read-only codebase investigation:

* **No Audio Integration**: In `c:\Users\valee\OneDrive\Desktop\ждж\дз\AURA Music\aure-music-v2\src\store\playerStore.ts`, the Zustand store manages standard playback fields (e.g., `isPlaying`, `currentTime`, `duration`, `volume`), but contains no references to a native `HTMLAudioElement`, `new Audio()`, or audio events. For example, the `isPlaying` action:
  ```typescript
  66:   setPlaying: (val) => set({ isPlaying: !!val }),
  ```
  and the volume updater:
  ```typescript
  72:   setVolume: (vol) => set({ volume: Math.max(0, Math.min(100, vol)) }),
  ```
  only set primitive store variables without any side-effects on hardware audio output.
* **Component-Level Slider Dispatches**: In `c:\Users\valee\OneDrive\Desktop\ждж\дз\AURA Music\aure-music-v2\src\components\ControlsBar.tsx`, the progress slider and volume slider dispatch values directly into the player store:
  ```typescript
  94:           onChange={(e) => setCurrentTime(Number(e.target.value))}
  ...
  115:           onChange={(e) => setVolume(Number(e.target.value))}
  ```
* **No Audio Mocking in Setup**: In `c:\Users\valee\OneDrive\Desktop\ждж\дз\AURA Music\aure-music-v2\src\tests\setup.ts`, there is no global mock for `window.Audio` or native HTML5 media capabilities:
  ```typescript
  1: import '@testing-library/jest-dom';
  ```
* **Hardcoded Playlist**: In `src/store/playerStore.ts`, the player store queue loops over a hardcoded playlist `STATIC_PLAYLIST`:
  ```typescript
  25: const STATIC_PLAYLIST: Track[] = [ ... ];
  ```

---

## 2. Logic Chain

1. Since `playerStore.ts` does not instantiate or listen to an `HTMLAudioElement` (Observation 1), the music player state is purely visual, and no real audio plays when the user triggers actions.
2. In order to play real music, we must initialize a native `HTMLAudioElement` instance and bind it to the Zustand store state.
3. Placing this instantiation as a module-level singleton within `playerStore.ts` ensures that it:
   - Remains persistent and decoupled from React rendering cycles.
   - Executes `.play()` synchronously in response to user events (e.g. clicking the play button in Observation 2), which is essential to satisfy strict browser autoplay policies.
4. Setting up a two-way synchronization via a Zustand state subscription (`usePlayerStore.subscribe`) and audio element event listeners allows updates to propagate seamlessly in both directions:
   - **Downstream (Store -> Audio)**: Updates source URL, changes playback mode, updates volume, and updates position.
   - **Upstream (Audio -> Store)**: Emits periodic `timeupdate` events to synchronize the slider position, tracks track duration dynamically via `durationchange`, and triggers `nextTrack()` when the audio ends.
5. To prevent infinite feedback loops (where the store updates the audio, which triggers an event that updates the store, repeating forever), we must introduce delta threshold checks:
   - Only update the store's `currentTime` if the player's native position deviates by more than `0.8s`.
   - Only update the audio element's `currentTime` (seek) if the store's `currentTime` deviates by more than `1.2s` (signaling a manual scrub by the user rather than normal progression).
6. Because the JSDOM test environment used by Vitest does not implement real media streaming methods (`play()`, `pause()`, etc.), running tests with a real `Audio` singleton will throw "Not implemented" errors or crash the test run. Therefore, we must implement a mock `Audio` factory inside `src/tests/setup.ts` to mimic event listeners and state properties (Observation 3).

---

## 3. Caveats

* **Autoplay Permissions**: While clicking elements will synchronously invoke the audio engine and bypass browser play restrictions, programmatically setting `isPlaying: true` on initial mount (without user interaction) will be blocked by browsers. This is handled gracefully by catching the promise returned by `audio.play()` and resetting the state.
* **Format Compatibility**: The implementation assumes browser support for the URLs returned by the mock API (typically `.mp3`). In production environments, checking file type support or using fallbacks may be required.
* **No dynamic queue logic yet**: Milestone 4.1 needs to replace `STATIC_PLAYLIST` with a dynamic `playlist` array in the store. This analysis assumes that the dynamic queue layout changes described in the blueprint are fully implemented.

---

## 4. Conclusion

A centralized two-way synchronization engine integrated directly inside `src/store/playerStore.ts` is the most robust and performant mechanism to connect the Zustand state and native `HTMLAudioElement`. It avoids common pitfalls such as React state rendering loops, asynchronous hook lags, and browser autoplay blocks. The proposed design updates `playerStore.ts` with a safe singleton, registers necessary events for progress sync, playlist loop progression, and network failure recovery, and adds a test environment mock for Vitest.

Detailed findings and implementation blueprints are documented in `.agents/teamwork_preview_explorer_m4_2/analysis.md`.

---

## 5. Verification Method

To verify the integration, the following steps must be completed:

1. **Test Execution**: Run the vitest test suite using the target command:
   ```bash
   npx vitest run
   ```
   All existing and new tests should pass without errors.
2. **Inspect Files**:
   - Verify `src/store/playerStore.ts` imports and creates the `HTMLAudioElement` singleton and establishes the subscribers.
   - Verify `src/tests/setup.ts` declares the global `Audio` mock.
3. **Invalidation Conditions**:
   - If Vitest tests crash with errors like `Not implemented: HTMLMediaElement.prototype.play`, it indicates that the JSDOM mock in `setup.ts` has not been loaded correctly or is incomplete.
   - If the player slider stutters or lags when dragged, it indicates that the asymmetric thresholds (e.g. `0.8s` and `1.2s`) are not functioning properly, allowing feedback loops to disrupt the UI thread.
