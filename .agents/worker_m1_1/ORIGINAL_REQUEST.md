## 2026-07-14T08:08:54Z
You are Milestone 1 Worker (identity: worker_m1_1).
Your working directory is: c:\Users\valee\OneDrive\Desktop\ждж\дз\AURA Music\.agents\worker_m1_1

Your task is to implement the project initialization and configuration for AURA Music v2.
Inputs:
- Read c:\Users\valee\OneDrive\Desktop\ждж\дз\AURA Music\.agents\sub_orch_m1\synthesis.md for the plan and configurations.
- Read c:\Users\valee\OneDrive\Desktop\ждж\дз\AURA Music\PROJECT.md.

Objective:
1. Scaffold the React + Vite + TypeScript application in folder `aure-music-v2` under the workspace root `c:\Users\valee\OneDrive\Desktop\ждж\дз\AURA Music\`.
2. Install production dependencies (`zustand`, `framer-motion`) and dev dependencies (`tailwindcss`, `postcss`, `autoprefixer`, `vitest`, `jsdom`, `@testing-library/react`, `@testing-library/jest-dom`, etc.) as planned in `synthesis.md`.
3. Set up and write configuration files inside `aure-music-v2/`:
   - `vite.config.ts` (with path alias `@/*` and Vitest options, plus Tauri optimizations)
   - `tailwind.config.js` and `postcss.config.js`
   - `eslint.config.js` (Flat config integrating Prettier)
   - `.prettierrc` and `.prettierignore`
   - `tsconfig.app.json` (add path alias `@/*` and Vitest global types)
4. Restructure directory:
   - Create directories: `src/components/`, `src/store/`, `src/api/`, `src/styles/`, `src/tests/`.
   - Write standard Tailwind CSS directives inside `src/styles/global.css`.
   - Clean up default template files: delete `App.css` and `index.css`, update imports in `main.tsx` and `App.tsx`.
5. Implement skeleton/boilerplate files matching PROJECT.md interface contracts:
   - `src/store/playerStore.ts` (Zustand player store skeleton)
   - `src/api/mockApi.ts` (Mock API clients)
   - `src/tests/setup.ts` (Vitest DOM matchers setup)
   - `src/tests/example.test.tsx` (Verification test asserting dummy component and Testing Library works)
6. Verify development scripts inside `aure-music-v2/package.json`:
   - Ensure `npm run build`, `npm run lint`, and `npm test` are fully functional.
   - Run `npm run build` to verify compilation works.
   - Run `npm run lint` to verify eslint passes with 0 warnings.
   - Run `npm test` to verify Vitest tests run and pass 100%.

MANDATORY INTEGRITY WARNING:
> DO NOT CHEAT. All implementations must be genuine. DO NOT
> hardcode test results, create dummy/facade implementations, or
> circumvent the intended task. A Forensic Auditor will independently
> verify your work. Integrity violations WILL be detected and your
> work WILL be rejected.

Output requirements:
Write your implementation details to `c:\Users\valee\OneDrive\Desktop\ждж\дз\AURA Music\.agents\worker_m1_1\changes.md` and complete your handoff. Ensure you report build, lint, and test commands and their results in your handoff. Send a message back to the parent when complete.
