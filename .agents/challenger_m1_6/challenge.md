# Challenge Report — 2026-07-14T15:58:00+03:00

## Challenge Summary

**Overall risk assessment**: LOW

All development tools (TypeScript compiler with project references, ESLint with zero-warning threshold, and Vitest with JSDOM) are correctly configured and functional. They respond quickly and catch errors reliably.

## Challenges

### [Low] Challenge 1: Solution-Style TypeScript Project Reference Loophole

- **Assumption challenged**: The build script (`tsc`) alone checks all files for type safety.
- **Attack scenario**: In solution-style TS setups, `tsc` without the build flag (`-b`) ignores project references, which can allow type errors to pass in CI pipelines.
- **Blast radius**: Developers could push type-broken code to production since Vite does not block on type safety (it only transpiles).
- **Mitigation**: Confirmed that `package.json` now uses `tsc -b && vite build`. We tested introducing a type error in `playerStore.ts` (assigning a string to a number volume property) and verified that `npm run build` failed correctly with exit code 1.

### [Low] Challenge 2: ESLint Warning Toleration

- **Assumption challenged**: ESLint is active, but warnings might be ignored in CI.
- **Attack scenario**: Code with unused variables or React Hook order violations gets merged because ESLint passes on warnings.
- **Blast radius**: Code quality degrades, leading to memory leaks or hook lifecycle bugs.
- **Mitigation**: The command `eslint . --max-warnings 0` is used. We tested introducing an unused variable and a conditional Hook call (`useState` inside an `if` block) in `App.tsx` and verified it is caught, exiting with code 1.

### [Low] Challenge 3: Vitest Browser Environment Dependency

- **Assumption challenged**: Vitest environment defaults to `node`, which lack DOM APIs.
- **Attack scenario**: React components using hooks or DOM references fail to render in unit tests.
- **Blast radius**: 100% of frontend rendering tests fail.
- **Mitigation**: Confirmed `environment: 'jsdom'` is configured in `vite.config.ts`. Verified that `should verify JSDOM environment is active` test successfully runs and asserts `window` and `document` are objects, and `navigator.userAgent` contains `'jsdom'`.

## Stress Test Results

- **Introduce TypeScript Type Error** (string assigned to `volume` in `playerStore.ts`) → `npm run build` must fail → **PASSED** (failed with TS2322 error and exit code 1).
- **Introduce ESLint Warning** (unused variable in `App.tsx`) → `npm run lint` must fail → **PASSED** (failed with no-unused-vars error and exit code 1).
- **Introduce Test Failure** (`expect(1).toBe(2)` in `example.test.tsx`) → `npm test` must fail → **PASSED** (failed with AssertionError and exit code 1).
- **Verify JSDOM Mocking** (execute tests asserting window/document presence) → JSDOM variables present and userAgent includes 'jsdom' → **PASSED** (tests executed successfully and passed).

## Unchallenged Areas

- **E2E Browser Interaction** — actual browser execution (using Playwright or Selenium) was not challenged as it is out of scope for Milestone 1 unit/integration configuration.
