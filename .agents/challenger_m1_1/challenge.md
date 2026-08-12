# Challenge Report - Milestone 1 Setup

**Overall risk assessment**: HIGH

## Challenges

### [High] TypeScript compilation does not typecheck the project during build
- **Assumption challenged**: Running `npm run build` checks TypeScript types and fails on type violations.
- **Attack scenario**: A developer introduces a type violation (e.g., assigning a string to a number in `src/App.tsx` or `src/store/playerStore.ts`). When `npm run build` is executed, `tsc` exits successfully with exit code 0 because the root `tsconfig.json` contains references to child configurations (`tsconfig.app.json`, `tsconfig.node.json`) and no files of its own. Running `tsc` without `-b` or `--build` fails to compile references in solution-style TypeScript projects. Thus, Vite compiles the project without type safety, allowing broken code to be built and deployed.
- **Blast radius**: Undetected type errors in production builds.
- **Mitigation**: Update the `"build"` script in `package.json` to use `"tsc -b && vite build"` instead of `"tsc && vite build"`.

### [Low] JSDOM environment mocking limitations
- **Assumption challenged**: JSDOM behaves exactly like a real browser environment.
- **Attack scenario**: Tests checking complex visual layouts, media element events (e.g., `<audio>` play state events), custom scrollbars, or computed styles will not fully compute or fire correctly since JSDOM does not render a real layout or run a browser layout engine.
- **Blast radius**: Test assertions checking CSS styles or layout dimensions (widths/heights) will return mock values or fail, forcing reliance on raw classes or inline styles.
- **Mitigation**: Add unit-level mocking for browser APIs (like `HTMLAudioElement` play/pause functions and properties) and focus layout-sensitive validations on E2E testing using Playwright/Cypress.

## Stress Test Results

- **TypeScript type violation** → `npm run build` should fail → It completed successfully with exit code 0 (FAIL)
- **ESLint syntax warning/error** → `npm run lint` should fail → It failed with exit code 1 showing the unused variable error (PASS)
- **Test assertion failure** → `npm test` should fail → It failed with exit code 1 showing the failed assertion (PASS)
- **JSDOM environment validation** → Assertions check for `window`, `document`, and `navigator.userAgent` → Tests pass showing JSDOM is active (PASS)

## Unchallenged Areas
- None.
