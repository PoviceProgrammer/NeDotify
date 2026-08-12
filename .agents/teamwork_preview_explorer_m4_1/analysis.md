# Milestone 4 - Animations & Audio Analysis Report

This report provides a read-only investigation and proposal for Milestone 4 (Animations & Audio). It examines the architecture of the mock API, the Zustand player store, test configurations, and details a robust implementation strategy for dynamic queue management and HTML5 audio synchronization.

---

## 1. Codebase Architecture Findings

Based on our exploration of the codebase:
- **Layout & Entry Point**: The main player component is `src/components/AurePlayer.tsx`. It handles loading tracks from the API layer via a local `useState` hook and detects OS platforms (`macos`, `windows`, `other`) to configure custom layout class names.
- **State Management**: `src/store/playerStore.ts` (re-exported by `src/store/usePlayerStore.ts`) manages the player state (theme engine, transparency mode, playback play/pause state, volume, track progression). Currently, queue cycling (`nextTrack`, `prevTrack`) is hardcoded to a static list `STATIC_PLAYLIST`.
- **Mock API**: `src/api/mockApi.ts` currently provides `getTracks()`, returning three mock tracks (`Aura of Light`, `Neon Dreams`, `Ocean Breeze`) after a simulated network delay of 10ms.
- **Testing Infrastructure**: The test environment uses **Vitest** + **Testing Library** + **JSDOM** (`setup.ts` loads `@testing-library/jest-dom` matchers). Tests are defined under `src/tests/` and cover init stubs, boundary stress cases, and four tiers of E2E coverage.

---

## 2. Mock API Design Proposal

To support server-delayed tracklists and detail fetches, we propose expanding `src/api/mockApi.ts` as follows:

### Proposal: Asynchronous Track Detail Fetches & Configurable Server Delay
1. **Dynamic Track Retrieval**: Add `getTrackDetails(id: string): Promise<Track>` to retrieve track data by ID.
2. **Realistic Network Latency**: Introduce a configurable delay (e.g., defaulting to 100ms) or custom timing options to simulate authentic network retrieval.
3. **Deep Copy Returns**: Always map or copy track objects before resolving to prevent mutation of the original mock list (referential isolation).
4. **Error Simulation**: Provide simulated network failure modes (e.g. optional arguments to throw/reject promises) to verify UI recovery and error state transitions.

### Proposed Code Snippet for `src/api/mockApi.ts`:
```typescript
export interface Track {
  id: string;
  title: string;
  artist: string;
  album: string;
  duration: number;
  coverUrl: string;
  audioUrl: string;
}

const mockTracks: Track[] = [
  {
    id: '1',
    title: 'Aura of Light',
    artist: 'Lumina',
    album: 'Ethereal Vibes',
    duration: 180,
    coverUrl: 'https://example.com/cover1.jpg',
    audioUrl: 'https://example.com/audio1.mp3'
  },
  {
    id: '2',
    title: 'Neon Dreams',
    artist: 'Synthwave Kid',
    album: 'Retro Wave',
    duration: 210,
    coverUrl: 'https://example.com/cover2.jpg',
    audioUrl: 'https://example.com/audio2.mp3'
  },
  {
    id: '3',
    title: 'Ocean Breeze',
    artist: 'Nature Echoes',
    album: 'Relaxation',
    duration: 240,
    coverUrl: 'https://example.com/cover3.jpg',
    audioUrl: 'https://example.com/audio3.mp3'
  }
];

export async function getTracks(options?: { delayMs?: number; forceFail?: boolean }): Promise<Track[]> {
  return new Promise((resolve, reject) => {
    const delay = options?.delayMs ?? 100;
    setTimeout(() => {
      if (options?.forceFail) {
        reject(new Error('Network failure'));
        return;
      }
      // Return fresh objects to prevent shared state contamination
      resolve(mockTracks.map(track => ({ ...track })));
    }, delay);
  });
}

export async function getTrackDetails(id: string, options?: { delayMs?: number }): Promise<Track> {
  return new Promise((resolve, reject) => {
    const delay = options?.delayMs ?? 100;
    setTimeout(() => {
      const track = mockTracks.find(t => t.id === id);
      if (!track) {
        reject(new Error(`Track with ID ${id} not found`));
        return;
      }
      resolve({ ...track });
    }, delay);
  });
}
```

---

## 3. Zustand Player Store Queue Management Proposal

Currently, the Zustand store (`src/store/playerStore.ts`) loops through a hardcoded `STATIC_PLAYLIST`. We propose introducing dynamic queue management into the Zustand store to make the playback queue dynamic and fully integrated with the API.

### Proposal: State and Action Additions
1. **State Addition**: Add `queue: Track[]` to store track sequences.
2. **Dynamic Queue Actions**:
   - `setQueue(tracks: Track[])`: Replaces the current playlist queue.
   - `loadTracksFromApi()`: Asynchronously fetches tracks from the mock API and updates the queue.
3. **Queue Cycling Refactoring**: Refactor `nextTrack` and `prevTrack` to read from the dynamic `queue` state. Handle boundaries:
   - Empty queue resets state.
   - Circular wrapping using modulo operators: `(index + 1) % queue.length`.
   - Missing current track defaults playback to index `0` of the queue.

### Proposed Code Snippet for `src/store/playerStore.ts`:
```typescript
import { create } from 'zustand';
import { Track, getTracks } from '../api/mockApi';

export type ThemeName = string;

export interface PlayerState {
  isTransparencyEnabled: boolean;
  theme: ThemeName;
  currentTrack: Track | null;
  isPlaying: boolean;
  volume: number; // 0-100
  currentTime: number;
  duration: number;
  queue: Track[]; // Dynamic Queue
  
  setTransparencyEnabled: (val: boolean) => void;
  setTheme: (theme: ThemeName) => void;
  setPlaying: (val: boolean) => void;
  setCurrentTrack: (track: Track | null) => void;
  setVolume: (vol: number) => void;
  setCurrentTime: (time: number) => void;
  
  setQueue: (tracks: Track[]) => void;
  loadTracksFromApi: () => Promise<void>;
  
  nextTrack: () => void;
  prevTrack: () => void;
}

export const usePlayerStore = create<PlayerState>((set, get) => ({
  isTransparencyEnabled: false,
  theme: 'aura-dark',
  currentTrack: null,
  isPlaying: false,
  volume: 50,
  currentTime: 0,
  duration: 0,
  queue: [],

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

  setQueue: (tracks) => set({ queue: tracks }),
  loadTracksFromApi: async () => {
    try {
      const tracks = await getTracks();
      set({ queue: tracks });
      const { currentTrack } = get();
      if (!currentTrack && tracks.length > 0) {
        set({
          currentTrack: tracks[0],
          duration: tracks[0].duration,
          currentTime: 0
        });
      }
    } catch (error) {
      console.error('Failed to load tracks:', error);
    }
  },

  nextTrack: () => {
    const { currentTrack, queue } = get();
    if (queue.length === 0) {
      set({ currentTrack: null, currentTime: 0, duration: 0 });
      return;
    }
    if (!currentTrack) {
      const track = queue[0];
      set({ currentTrack: track, duration: track.duration, currentTime: 0 });
      return;
    }
    const idx = queue.findIndex(t => t.id === currentTrack.id);
    if (idx === -1) {
      const track = queue[0];
      set({ currentTrack: track, duration: track.duration, currentTime: 0 });
      return;
    }
    const nextIdx = (idx + 1) % queue.length;
    const track = queue[nextIdx];
    set({
      currentTrack: track,
      duration: track.duration,
      currentTime: 0
    });
  },

  prevTrack: () => {
    const { currentTrack, queue } = get();
    if (queue.length === 0) {
      set({ currentTrack: null, currentTime: 0, duration: 0 });
      return;
    }
    if (!currentTrack) {
      const track = queue[0];
      set({ currentTrack: track, duration: track.duration, currentTime: 0 });
      return;
    }
    const idx = queue.findIndex(t => t.id === currentTrack.id);
    if (idx === -1) {
      const track = queue[0];
      set({ currentTrack: track, duration: track.duration, currentTime: 0 });
      return;
    }
    const prevIdx = (idx - 1 + queue.length) % queue.length;
    const track = queue[prevIdx];
    set({
      currentTrack: track,
      duration: track.duration,
      currentTime: 0
    });
  },
}));
```

---

## 4. Audio Playback Engine Integration Strategy

To synchronize the Zustand store state with HTML5 `Audio`, we propose two strategies for subsequent milestones:

### Strategy A: Globally Subscribed Audio Engine Singleton (Recommended)
This approach completely decouples the audio lifecycle from React's rendering and updates, preventing duplicate audio elements.

1. **Audio Instance**: Instantiate `new Audio()` inside a singleton class.
2. **Store Subscription**: Use `usePlayerStore.subscribe` to monitor state updates and apply changes:
   - When `currentTrack` changes, set `audio.src = track.audioUrl`.
   - When `isPlaying` changes, call `audio.play()` or `audio.pause()`.
   - When `volume` changes, update `audio.volume = volume / 100`.
   - When `currentTime` is scrubbed (e.g. difference between `audio.currentTime` and store time > 1.5s), set `audio.currentTime`.
3. **Event Listener Sync**: Add native listeners (`timeupdate`, `durationchange`, `ended`, `play`, `pause`) that update Zustand states (`setCurrentTime`, `setDuration`, `nextTrack`, `setPlaying`).
4. **Infinite Loop Protection**: Ensure changes back-and-forth do not create recursive trigger loops (e.g. only update audio element's time if the delta is significant).

### Strategy B: React Component Ref Sync
Sync Zustand state via React hooks inside a component using `audioRef` (e.g., `<audio ref={audioRef} ... />`).
- *Pros*: Natural React hook structure.
- *Cons*: Prone to race conditions on quick mounting/unmounting, and audio playback interrupts when components re-render or relocate.

---

## 5. Testing & Environment Analysis

### Test Execution Commands
- Run Tests: `npm test` or `npx vitest run` in the `aure-music-v2` directory.
- Watch Mode: `npx vitest`

### Vitest Config (`vite.config.ts`)
- Target: JSDOM (`environment: 'jsdom'`) simulating a web browser.
- Global functions: `globals: true` (e.g., `describe`, `it`, `expect` are globally available).
- Setup file: `./src/tests/setup.ts` imports `@testing-library/jest-dom` to support custom matchers.

### Critical Testing Caveat (HTML5 Audio Mocking)
JSDOM does not implement media element loading or playing APIs (e.g., `play()`, `pause()`, `load()`). To run test suites successfully when audio playback sync is implemented, these methods must be mocked in `src/tests/setup.ts`:
```typescript
window.HTMLMediaElement.prototype.play = vi.fn().mockImplementation(() => Promise.resolve());
window.HTMLMediaElement.prototype.pause = vi.fn();
window.HTMLMediaElement.prototype.load = vi.fn();
```
Failure to mock these will cause tests asserting on playback controls to crash or throw errors in JSDOM.
