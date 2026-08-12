# Challenge Report - Milestone 1 Setup Verification

## Challenge Summary

**Overall risk assessment**: HIGH

While the development tooling (ESLint, Vitest, JSDOM) is responsive and functional, there is a critical vulnerability in the project compilation pipeline: **TypeScript compilation errors are completely silent and bypassed during `npm run build`**. As a result, pre-existing type violations (such as `volume` initialized to the string `'fifty'` instead of a number, and unused imports) were not caught by the build script, allowing the production build to compile successfully despite these type errors.

---

## Challenges

### [High] Challenge 1: Silent TypeScript Type Verification Bypass in Build Command

- **Assumption challenged**: The build script `npm run build` will perform strict type verification and fail if there are any TypeScript compilation errors.
- **Attack scenario**: A developer runs `npm run build` which runs `tsc && vite build`. Since the parent `tsconfig.json` contains only project references (`tsconfig.app.json` and `tsconfig.node.json`) and no direct files, `tsc` without the `--build` or `-b` flag does not compile or check any of the referenced projects. It immediately exits with code `0`. Vite then builds the project using `esbuild` (which transpile TypeScript by removing type annotations and does not do type-checking).
- **Blast radius**: A production build can be generated and deployed with severe type mismatches. For example, `playerStore.ts` initializes `volume` to the string `'fifty'` despite the interface `PlayerState` typing it strictly as a `number`. This will cause runtime failures in component sliders or calculation logic.
- **Mitigation**: Update the build script in `package.json` to use `--build` (or `-b`) flag:
  ```json
  "build": "tsc -b && vite build"
  ```
  Alternatively, explicitly compile the app configuration:
  ```json
  "build": "tsc -p tsconfig.app.json && vite build"
  ```

### [Medium] Challenge 2: ESLint Lacks Type-Aware Rules Configuration

- **Assumption challenged**: ESLint (`npm run lint`) checks syntax and flags standard type-related errors during development.
- **Attack scenario**: A developer relies on `npm run lint` to find code issues. However, since ESLint is configured without type-aware parser options (no `parserOptions.project` in `eslint.config.js`), type mismatch issues (like assigning a string to a number variable) are completely ignored by the linter.
- **Blast radius**: When combined with the silent `tsc` build issue, type violations can persist indefinitely in the repository without being detected by local linters or builds.
- **Mitigation**: Ensure `tsc -b` is run as part of the linting process or configure type-aware linting in ESLint.

---

## Stress Test Results

| Test Scenario | Expected Behavior | Actual Behavior | Pass/Fail |
|---|---|---|---|
| **TypeScript check on build (with error)** | `npm run build` fails and prints error | Build completes successfully with exit code 0 | **FAIL** |
| **Pristine project strict type-check (`tsc -b`)** | Compiles cleanly with no type errors | Fails on `volume: 'fifty'` in `playerStore.ts` and unused `React` import in `example.test.tsx` | **FAIL** |
| **ESLint syntax check (with unused var)** | `npm run lint` fails with exit code 1 and prints warning/error | Fails with exit code 1 and prints `'unusedVal' is assigned a value but never used` | **PASS** |
| **Test runner error verification** | `npm test` fails with exit code 1 and shows failing assertion | Fails with exit code 1 showing the mismatch in assertion | **PASS** |

---

## Performance Bottlenecks

1. **JSDOM Startup Overhead**: During `npm test`, the Vitest environment setup takes around 3.5 - 6.5 seconds. For a small suite of 86 simple tests, the actual test execution takes only ~1.3 seconds. This startup overhead makes local TDD runs slightly slower than necessary.
2. **Build and Transpilation Speed**: Vite (via esbuild) compiles the production bundle in under 900ms. This is highly performant and has no bottlenecks.

---

## Unchallenged Areas

- **Audio Playback Engine**: Real audio playback logic using HTML5 Audio elements is not yet implemented. JSDOM does not natively support media playback APIs (`HTMLMediaElement.prototype.play`/`pause`), which will cause tests to throw errors once the real audio engine is integrated in Milestone 4 unless these methods are explicitly mocked.
