## 2026-07-14T08:08:02Z
You are a worker agent for Milestone 1: Environment Setup & Stubs.
Your working directory is: c:\Users\valee\OneDrive\Desktop\ждж\дз\AURA Music\.agents\worker_m1

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A Forensic Auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Your tasks:
1. Initialize the directory `aure-music-v2` under `c:\Users\valee\OneDrive\Desktop\ждж\дз\AURA Music\` if it doesn't exist.
2. Create `package.json` with the following configuration:
   - react, react-dom, zustand, framer-motion.
   - devDependencies: typescript, vitest, jsdom, @testing-library/react, @testing-library/jest-dom, @types/react, @types/react-dom.
   - Script: "test": "vitest run".
3. Create `tsconfig.json` configured for React, ESM, and Vitest.
4. Create `vitest.config.ts` (or `vite.config.ts` configuring Vitest) with `environment: 'jsdom'`.
5. Create stub source files under `src/` that define the interfaces specified in PROJECT.md:
   - `src/store/usePlayerStore.ts` (Zustand store containing: `isTransparencyEnabled`, `setTransparencyEnabled`, `theme`, `setTheme`, `currentTrack`, `isPlaying`, `volume`, `currentTime`, `duration`, `setPlaying`, `setCurrentTrack`, `setVolume`, `setCurrentTime`, `nextTrack`, `prevTrack`)
   - `src/api/mockApi.ts` (defining `Track` interface and exporting `getTracks()` returning `Promise<Track[]>`)
   - `src/components/AurePlayer.tsx` (simple functional React component rendering a skeleton layout of the player, e.g., divs for Sidebar, Main Content, Controls bar, and controls with data-testids: 'sidebar', 'play-pause-button', 'next-button', 'prev-button', 'cover-art', 'volume-slider', 'progress-slider', 'transparency-toggle', and theme swatches)
6. Write a dummy test `src/tests/init.test.ts` that imports the stubs and does a trivial assertion (e.g. checking that the store is initialized or `getTracks` is a function), to verify the Vitest test environment works.
7. Run `npm install` or ensure the packages can run. Note that you may need to run `npm i` or run vitest directly with npx. Run `npx vitest run` to verify that the environment is set up and the dummy test passes.
8. Document all created files and the output of the test run in `c:\Users\valee\OneDrive\Desktop\ждж\дз\AURA Music\.agents\worker_m1\handoff.md`.
9. Send a message to your parent conversation ID (sub_orch_testing_track) when done.
