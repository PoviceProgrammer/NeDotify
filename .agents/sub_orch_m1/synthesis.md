# Synthesized Milestone 1 (Project Init) Plan

## Overview
All three Explorers completed their analyses, verifying that there are no folder or file name conflicts in the root workspace. The folder `aure-music-v2` does not exist and can be safely scaffolded.

## Proposed Strategy
1. **Scaffolding**: Initialize React + Vite + TypeScript frontend inside `aure-music-v2` using the standard `react-ts` template.
2. **Dependencies**:
   - Runtime: `zustand`, `framer-motion`
   - Dev: `tailwindcss`, `postcss`, `autoprefixer`, `vitest`, `jsdom`, `@testing-library/react`, `@testing-library/jest-dom`, `@types/react`, `@types/react-dom`, `@types/node`, `prettier`, `eslint-config-prettier`, `eslint`, etc.
3. **Configurations**:
   - `vite.config.ts`: Configured for React + Vitest (`jsdom`) + path alias `@/*` -> `src/*` + Tauri optimizations (server port 1420, strictPort, clearScreen, TAURI_ env prefix).
   - `tailwind.config.js` & `postcss.config.js`: Tailwind CSS integration.
   - `eslint.config.js`: Modern flat configuration integrating Prettier to prevent rules conflict.
   - `.prettierrc` & `.prettierignore`: Code formatting styling.
   - `tsconfig.app.json`: Updated for path alias and Vitest globals types.
4. **Folder Structure**:
   - `src/components/`
   - `src/store/`
   - `src/api/`
   - `src/styles/`
   - `src/tests/`
5. **Code Boilerplate & Tests**:
   - `src/styles/global.css`: Standard Tailwind directives.
   - `src/tests/setup.ts`: Vitest DOM matchers setup.
   - `src/tests/example.test.tsx`: Sanity check test.
   - `src/store/playerStore.ts` & `src/api/mockApi.ts`: Boilerplate interface skeletons matching `PROJECT.md` contracts.
   - Clean up default scaffold files (`src/App.css`, `src/index.css`). Update `main.tsx` and `App.tsx` imports.
6. **Execution Commands**:
   - `npm run build`: `tsc && vite build`
   - `npm run lint`: `eslint . --max-warnings 0`
   - `npm test`: `vitest run`
