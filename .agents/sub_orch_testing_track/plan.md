# Plan: E2E Test Suite for Aure Music v2

This plan breaks down the development of the E2E test suite into concrete, verifiable steps.

## Phase 1: Environment Setup and Interface Stubs (Milestone 1)
- [ ] Step 1.1: Verify if `aure-music-v2` directory exists. If not, create it.
- [ ] Step 1.2: Initialize a basic Node/npm project inside `aure-music-v2` (package.json).
- [ ] Step 1.3: Configure Vitest and React Testing Library (vitest.config.ts, tsconfig.json).
- [ ] Step 1.4: Create stub source files under `src/` to satisfy imports for the E2E tests:
  - `src/store/usePlayerStore.ts` (Zustand player store interface)
  - `src/api/mockApi.ts` (Mock API interface and shape definitions)
  - `src/components/AurePlayer.tsx` (Core layout component UI interface)
- [ ] Step 1.5: Verify configuration by running a basic test runner command.

## Phase 2: Design and Implement E2E Test Cases (Milestone 2)
- [ ] Step 2.1: Enumerate the 77+ test cases spanning Tiers 1-4.
- [ ] Step 2.2: Write the Tier 1 Feature Coverage tests (35 cases) in `src/tests/e2e/tier1.test.tsx` or similar.
- [ ] Step 2.3: Write the Tier 2 Boundary & Corner cases (35 cases) in `src/tests/e2e/tier2.test.tsx` or similar.
- [ ] Step 2.4: Write the Tier 3 Cross-Feature combination tests (7 cases) in `src/tests/e2e/tier3.test.tsx` or similar.
- [ ] Step 2.5: Write the Tier 4 Real-World Application workload tests (5 cases) in `src/tests/e2e/tier4.test.tsx` or similar.

## Phase 3: Validation, Publishing and Handoff (Milestone 3)
- [ ] Step 3.1: Execute the test suite using Vitest to ensure all tests compile and run (they should fail on the stubs, which is expected, or pass if they test contract shapes - we must check the runner output).
- [ ] Step 3.2: Write and publish `TEST_INFRA.md` in the root folder.
- [ ] Step 3.3: Write and publish `TEST_READY.md` in the root folder.
- [ ] Step 3.4: Write `handoff.md` and report success to the parent.
