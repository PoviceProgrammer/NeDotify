# Analysis & Implementation Strategy: HTML5 Audio Sync with Zustand Store

This document outlines the architectural design and implementation details for Milestone 4.2 (HTML5 Audio Sync) in Aure Music v2. It provides a complete, robust plan to bind the Zustand store state (`isPlaying`, `currentTime`, `duration`, `volume`) to a native `HTMLAudioElement` instance.

---

## 1. Context and Current State Analysis

Currently, the Aure Music player state is managed in `src/store/playerStore.ts` using Zustand. The UI components (e.g., `ControlsBar.tsx`, `MainPanel.tsx`) read and write to this store to simulate actions:
- `isPlaying`: Toggles UI state between "Play" and "Pause".
- `currentTime` and `duration`: Represent playback progress, but are only updated manually or simulated.
- `volume`: Ranges from 0 to 100, driving the volume slider.
- `currentTrack`: Contains track metadata (including `audioUrl` and `duration`).

However, **there is currently no actual HTML5 Audio playback implementation**. The audio elements are not instantiated, and the actions have no side effects on real audio rendering.

---

## 2. Proposed Architecture: Two-Way Synchronization

To integrate real audio playback, we must bind the Zustand store to a single, shared `HTMLAudioElement` instance. 

### Why a Module-Level Singleton is Best
Instead of instantiating the `Audio` element in a React component and syncing via `useEffect` hooks, the native `HTMLAudioElement` will be instantiated as a **module-level singleton** inside `playerStore.ts` and managed directly via a Zustand subscriber.

This approach offers critical advantages:
1. **Direct Synchronous Callstack for Playback**: Modern browsers block `audio.play()` unless it is called directly within a user-gesture callstack (like a click event). Since Zustand state changes and subscribers run synchronously in the same callstack, calling `audio.play()` within the subscriber ensures the browser allows playback. React's asynchronous `useEffect` scheduling can run in a separate event tick, triggering autoplay blocks.
2. **Prevention of Feedback Loops**: Synchronizing state both ways (Audio -> Store and Store -> Audio) is prone to feedback loops. A central store subscriber with precise delta-guards easily breaks this loop.
3. **Decoupled Life Cycle**: Audio playback continues smoothly regardless of which components mount, unmount, or re-render.
4. **Simple Test Mocking**: The singleton is easy to bypass or mock in JSDOM / Vitest.

---

## 3. Sync Mechanics (Two-Way Binding)

The sync engine handles data flow in both directions:

### A. Downstream Sync: Zustand Store $\rightarrow$ HTMLAudioElement
We use a store subscriber (`usePlayerStore.subscribe`) to monitor store mutations and apply them to the native audio element:
1. **Track Changes (`currentTrack`)**:
   - If `currentTrack` changes, update `audio.src = track.audioUrl`, call `audio.load()`.
   - If the player is already playing (`isPlaying === true`), trigger `audio.play()`.
   - If `currentTrack` is null, set `audio.src = ''` and call `audio.pause()`.
2. **Playback State (`isPlaying`)**:
   - If `isPlaying` changes to `true`, call `audio.play()`.
   - If `isPlaying` changes to `false`, call `audio.pause()`.
   - Always catch play promise rejections: `.catch(err => { ... setPlaying(false); })`.
3. **Volume (`volume`)**:
   - When the store volume changes, scale it to a 0.0–1.0 float and apply it: `audio.volume = volume / 100`.
4. **Seeking/Scrubbing (`currentTime`)**:
   - When the user scrubs the progress slider, it updates `currentTime`.
   - To prevent the audio element from resetting its position repeatedly on natural playback ticks, only update `audio.currentTime` if the difference between the store's `currentTime` and `audio.currentTime` is greater than a threshold (e.g. `1.2s`).

### B. Upstream Sync: HTMLAudioElement $\rightarrow$ Zustand Store
We register event listeners on the `HTMLAudioElement` to keep the store updated:
1. **`timeupdate` Event**:
   - Periodically triggered by the native audio engine during playback.
   - Updates the store's `currentTime`. To avoid infinite feedback loops and minimize React rendering stress, only dispatch a store update if the difference between `audio.currentTime` and the store's current time exceeds `0.8s`.
2. **`durationchange` / `loadedmetadata` Events**:
   - Updates the store's `duration` with the actual file duration (`audio.duration`) once it is retrieved.
3. **`ended` Event**:
   - Automatically triggers the `nextTrack()` store action to cycle through the queue when a song finishes.
4. **`error` Event**:
   - Resets `isPlaying` to `false` in the store if the audio file fails to load (e.g. 404 URL).

---

## 4. Edge Cases & Solutions

| Edge Case | Impact | Mitigation Strategy |
|---|---|---|
| **Browser Autoplay Block** | UI shows "Pause" but no audio plays. | Catch play promise rejections: `audio.play().catch(...)`. If blocked, revert `isPlaying` in the store to `false`. |
| **Play/Pause Promise Collision** | Rapid user clicking throws `AbortError` because `pause()` interrupted `play()`. | The `.catch(...)` statement on `play()` prevents this error from crashing the application. |
| **Progress/Time Feedback Loop** | Store updates audio, which triggers `timeupdate`, which updates store. | Use asymmetric thresholds: only update store if delta > `0.8s`; only update audio if delta > `1.2s`. |
| **JSDOM environment in Vitest** | `window.Audio` is missing or throws "Not implemented" errors. | 1. Implement a safe environment guard when initializing the audio singleton in `playerStore.ts`. <br>2. Add a global Mock Audio mock in `src/tests/setup.ts` to mock native methods. |

---

## 5. Mock API & Queue Integration (Milestones 4.1 & 4.2 Sync)

To support dynamic track loading from the Mock API:
1. Extend `PlayerState` interface with a `playlist` state variable and a `setPlaylist` action.
2. Update `nextTrack` and `prevTrack` to search inside this dynamic `playlist` instead of the hardcoded `STATIC_PLAYLIST`.
3. In `AurePlayer.tsx`, fetch tracks from the API and populate the store playlist.

---

## 6. Implementation Patch Blueprint

Below is the proposed implementation patch for `src/store/playerStore.ts`.

```typescript
import { create } from 'zustand';
import { Track } from '../api/mockApi';

export type ThemeName = string;

export interface PlayerState {
  isTransparencyEnabled: boolean;
  theme: ThemeName;
  currentTrack: Track | null;
  isPlaying: boolean;
  volume: number; // 0-100
  currentTime: number;
  duration: number;
  playlist: Track[]; // Milestone 4.1: Dynamic queue
  
  setTransparencyEnabled: (val: boolean) => void;
  setTheme: (theme: ThemeName) => void;
  setPlaying: (val: boolean) => void;
  setCurrentTrack: (track: Track | null) => void;
  setVolume: (vol: number) => void;
  setCurrentTime: (time: number) => void;
  setPlaylist: (tracks: Track[]) => void; // Milestone 4.1
  nextTrack: () => void;
  prevTrack: () => void;
}

// Safe native Audio singleton initialization (with SSR and Testing support)
const audio: HTMLAudioElement | null =
  typeof window !== 'undefined' && typeof window.Audio !== 'undefined'
    ? new window.Audio()
    : null;

export const usePlayerStore = create<PlayerState>((set, get) => ({
  isTransparencyEnabled: false,
  theme: 'aura-dark',
  currentTrack: null,
  isPlaying: false,
  volume: 50,
  currentTime: 0,
  duration: 0,
  playlist: [],

  setTransparencyEnabled: (val) => set({ isTransparencyEnabled: !!val }),
  setTheme: (theme) => set({ theme }),
  setPlaying: (val) => set({ isPlaying: !!val }),
  setCurrentTrack: (track) => set({
    currentTrack: track,
    duration: track ? track.duration : 0,
    currentTime: 0
  }),
  setVolume: (vol) => set({ volume: Math.max(0, Math.min(100, vol)) }),
  setCurrentTime: (time) => set({ currentTime: time }),
  setPlaylist: (tracks) => set({ playlist: tracks }),
  nextTrack: () => {
    const { currentTrack, playlist } = get();
    if (!currentTrack || playlist.length === 0) {
      set({ currentTime: 0 });
      return;
    }
    const idx = playlist.findIndex(t => t.id === currentTrack.id);
    if (idx === -1) {
      set({ currentTime: 0 });
      return;
    }
    const nextIdx = (idx + 1) % playlist.length;
    const track = playlist[nextIdx];
    set({
      currentTrack: track,
      duration: track.duration,
      currentTime: 0
    });
  },
  prevTrack: () => {
    const { currentTrack, playlist } = get();
    if (!currentTrack || playlist.length === 0) {
      set({ currentTime: 0 });
      return;
    }
    const idx = playlist.findIndex(t => t.id === currentTrack.id);
    if (idx === -1) {
      set({ currentTime: 0 });
      return;
    }
    const prevIdx = (idx - 1 + playlist.length) % playlist.length;
    const track = playlist[prevIdx];
    set({
      currentTrack: track,
      duration: track.duration,
      currentTime: 0
    });
  },
}));

// Two-way synchronization engine
if (audio) {
  // Sync initial volume
  audio.volume = usePlayerStore.getState().volume / 100;

  // 1. UPSTREAM: Audio events update Zustand store state
  audio.addEventListener('timeupdate', () => {
    const storeTime = usePlayerStore.getState().currentTime;
    // Prevent feedback loops and excessive dispatches
    if (Math.abs(storeTime - audio.currentTime) > 0.8) {
      usePlayerStore.setState({ currentTime: audio.currentTime });
    }
  });

  audio.addEventListener('durationchange', () => {
    usePlayerStore.setState({ duration: audio.duration });
  });

  audio.addEventListener('ended', () => {
    usePlayerStore.getState().nextTrack();
  });

  audio.addEventListener('error', (e) => {
    console.error("HTMLAudioElement Error:", e);
    usePlayerStore.setState({ isPlaying: false });
  });

  // 2. DOWNSTREAM: Zustand store state updates Audio properties
  let prevTrackId = '';
  let prevIsPlaying = false;
  let prevVolume = -1;

  usePlayerStore.subscribe((state) => {
    const currentTrackId = state.currentTrack?.id || '';

    // A. Track Selection Change
    if (currentTrackId !== prevTrackId) {
      prevTrackId = currentTrackId;
      if (state.currentTrack) {
        audio.src = state.currentTrack.audioUrl;
        audio.load();
        if (state.isPlaying) {
          audio.play().catch((err) => {
            console.warn("Autoplay blocked:", err);
            usePlayerStore.setState({ isPlaying: false });
          });
        }
      } else {
        audio.src = '';
        audio.pause();
      }
    }

    // B. Playback State Toggle (Play/Pause)
    if (state.isPlaying !== prevIsPlaying) {
      prevIsPlaying = state.isPlaying;
      if (state.isPlaying) {
        if (audio.src) {
          audio.play().catch((err) => {
            console.warn("Play execution failed:", err);
            usePlayerStore.setState({ isPlaying: false });
          });
        }
      } else {
        audio.pause();
      }
    }

    // C. Volume Slider Adjustment
    if (state.volume !== prevVolume) {
      prevVolume = state.volume;
      audio.volume = state.volume / 100;
    }

    // D. Progress Slider Seeking / Dragging (Scrubbing)
    // Only update audio position if time difference is substantial (> 1.2s)
    if (Math.abs(audio.currentTime - state.currentTime) > 1.2) {
      audio.currentTime = state.currentTime;
    }
  });
}
```

---

## 7. Testing Environment Mocking (`src/tests/setup.ts`)

To ensure Vitest / JSDOM runs flawlessly with this integration, add a mock implementation of `Audio` in `src/tests/setup.ts`:

```typescript
import '@testing-library/jest-dom';
import { vi } from 'vitest';

// Global mock for HTML5 Audio element to prevent JSDOM errors
global.Audio = vi.fn().mockImplementation(() => {
  const listeners: Record<string, Function[]> = {};
  
  return {
    src: '',
    currentTime: 0,
    duration: 180,
    volume: 0.5,
    paused: true,
    
    addEventListener: vi.fn((event: string, callback: Function) => {
      if (!listeners[event]) listeners[event] = [];
      listeners[event].push(callback);
    }),
    removeEventListener: vi.fn((event: string, callback: Function) => {
      if (!listeners[event]) return;
      listeners[event] = listeners[event].filter(cb => cb !== callback);
    }),
    
    load: vi.fn(),
    play: vi.fn().mockImplementation(async function(this: any) {
      this.paused = false;
      // Simulate loadedmetadata event when source changes
      if (listeners['durationchange']) {
        listeners['durationchange'].forEach(cb => cb());
      }
    }),
    pause: vi.fn().mockImplementation(function(this: any) {
      this.paused = true;
    }),
  };
});
```
