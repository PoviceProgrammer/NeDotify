# Milestone 1 (Project Init) Requirements & Architecture Report

This report contains the workspace analysis, scaffolding instructions, package installation plans, configuration files, and step-by-step recommendations for Aure Music v2 frontend initialization.

---

## 1. Workspace Diagnostics & Conflict Check

A thorough examination of the workspace directory `c:\Users\valee\OneDrive\Desktop\ждж\дз\AURA Music\` was conducted:
- **No Existing Project Directory**: The subdirectory `aure-music-v2` does not exist. 
- **Conflicts**: There are no file or folder naming conflicts under the workspace directory for the `aure-music-v2` project.
- **Context**: The root workspace contains a Python backend / desktop app codebase (NeDotify) with files like `main.py`, directories like `audio/`, `services/`, `utils/`, etc. The new frontend will be isolated entirely within the `aure-music-v2` sub-folder, ensuring clean separation of concerns.

---

## 2. Project Scaffolding Strategy

To scaffold a React + Vite + TypeScript frontend under `aure-music-v2` non-interactively, run:
```bash
npm create vite@latest aure-music-v2 -- --template react-ts
```

### Folder Structure Adjustments
Following Vite scaffolding, the folder structure will be re-aligned to meet the `PROJECT.md` specifications:
- `aure-music-v2/`
  - `src/`
    - `components/` - React components (AurePlayer, Sidebar, Controls, Visualizer, etc.)
    - `store/` - Zustand stores (usePlayerStore)
    - `api/` - Mock API layer (mockApi)
    - `styles/` - Global styles, custom scrollbar, Tailwind directives
    - `tests/` - Unit and integration tests (Vitest + Testing Library)

---

## 3. Package Installation Plan

The following packages are required for the project. They will be installed after navigating to `aure-music-v2/`.

### Runtime Dependencies
These are necessary for the application's runtime features (animations, state management):
```bash
npm install zustand framer-motion
```

### Development Dependencies
These are necessary for compilation, linting, formatting, styling, and testing:
```bash
npm install -D tailwindcss postcss autoprefixer vitest jsdom @testing-library/react @testing-library/jest-dom @types/react @types/react-dom @types/node prettier eslint-config-prettier
```

---

## 4. Configuration File Drafts

### 4.1. Vite Configuration (`vite.config.ts`)
This configuration integrates React, Tailwind CSS, path aliasing (`@/`), and Vitest testing configuration. It also includes optimized Tauri properties (fixed development server port, disabled consoles, specific prefix).

```typescript
/// <reference types="vitest" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  // Dev server settings optimized for Tauri
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true,
    host: true,
  },
  envPrefix: ['VITE_', 'TAURI_'],
  // Testing settings
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/tests/setup.ts',
    css: true,
  },
});
```

### 4.2. Tailwind Configuration (`tailwind.config.js`)
Configured to look at modern React components and HTML entry points for CSS parsing:

```javascript
/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {},
  },
  plugins: [],
}
```

### 4.3. PostCSS Configuration (`postcss.config.js`)
Enables Tailwind and Autoprefixer parsing:

```javascript
export default {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
}
```

### 4.4. ESLint Configuration (`eslint.config.js`)
Using the modern ESLint flat config file to lint and prevent formatting conflicts:

```javascript
import js from '@eslint/js';
import globals from 'globals';
import reactHooks from 'eslint-plugin-react-hooks';
import reactRefresh from 'eslint-plugin-react-refresh';
import tseslint from 'typescript-eslint';
import prettierConfig from 'eslint-config-prettier';

export default tseslint.config(
  { ignores: ['dist', 'node_modules'] },
  {
    extends: [
      js.configs.recommended,
      ...tseslint.configs.recommended,
      prettierConfig
    ],
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'react-refresh/only-export-components': [
        'warn',
        { allowConstantExport: true },
      ],
      '@typescript-eslint/no-unused-vars': ['warn', { argsIgnorePattern: '^_' }]
    },
  }
);
```

### 4.5. Prettier Configuration (`.prettierrc`)
Consistent configuration for formatting:

```json
{
  "semi": true,
  "singleQuote": true,
  "tabWidth": 2,
  "trailingComma": "es5",
  "printWidth": 100,
  "endOfLine": "lf"
}
```

### 4.6. Prettier Ignore (`.prettierignore`)
```ignore
node_modules
dist
coverage
```

### 4.7. TypeScript Path Aliasing Config
In `tsconfig.app.json` (or `tsconfig.json` depending on scaffolding output), add the path resolving mapping:

```json
{
  "compilerOptions": {
    "baseUrl": ".",
    "paths": {
      "@/*": ["./src/*"]
    }
  }
}
```

### 4.8. Vitest Test Setup (`src/tests/setup.ts`)
Enables custom DOM assertions:

```typescript
import '@testing-library/jest-dom';
```

---

## 5. package.json Scripts Specification

Modify the scripts block in `aure-music-v2/package.json` to define build, lint, format, and test commands:

```json
"scripts": {
  "dev": "vite",
  "build": "tsc && vite build",
  "lint": "eslint . --report-unused-disable-directives --max-warnings 0",
  "format": "prettier --write \"src/**/*.{ts,tsx,css,md}\"",
  "test": "vitest run",
  "test:watch": "vitest"
}
```

*Note: The `test` script is mapped to `vitest run` so it executes once and exits cleanly, which is required for automated test suites and CI pipelines. Active development testing is run using `test:watch`.*

---

## 6. Implementation Scaffolding Snippets

To ensure all initial test setups and checks pass cleanly on project initialization, the following skeleton structures are recommended to be added to the project during setup:

### 6.1. Zustand Store Skeleton (`src/store/playerStore.ts`)
Based on the interface contract in `PROJECT.md`.

```typescript
import { create } from 'zustand';

export type ThemeName = string; // Placeholder for future theme structure

export interface Track {
  id: string;
  title: string;
  artist: string;
  album: string;
  duration: number;
  coverUrl: string;
  audioUrl: string;
}

export interface PlayerState {
  isTransparencyEnabled: boolean;
  setTransparencyEnabled: (val: boolean) => void;
  theme: ThemeName;
  setTheme: (theme: ThemeName) => void;
  currentTrack: Track | null;
  isPlaying: boolean;
  volume: number;
  currentTime: number;
  duration: number;
  setPlaying: (val: boolean) => void;
  setCurrentTrack: (track: Track) => void;
  setVolume: (vol: number) => void;
  setCurrentTime: (time: number) => void;
  nextTrack: () => void;
  prevTrack: () => void;
}

export const usePlayerStore = create<PlayerState>((set) => ({
  isTransparencyEnabled: true,
  setTransparencyEnabled: (val) => set({ isTransparencyEnabled: val }),
  theme: 'default',
  setTheme: (theme) => set({ theme }),
  currentTrack: null,
  isPlaying: false,
  volume: 80,
  currentTime: 0,
  duration: 0,
  setPlaying: (val) => set({ isPlaying: val }),
  setCurrentTrack: (track) => set({ currentTrack: track }),
  setVolume: (vol) => set({ volume: vol }),
  setCurrentTime: (time) => set({ currentTime: time }),
  nextTrack: () => {},
  prevTrack: () => {},
}));
```

### 6.2. Mock API Skeleton (`src/api/mockApi.ts`)
Based on the interface contract in `PROJECT.md`.

```typescript
import { Track } from '../store/playerStore';

export const getTracks = async (): Promise<Track[]> => {
  return [
    {
      id: '1',
      title: 'Mock Track 1',
      artist: 'Mock Artist 1',
      album: 'Mock Album 1',
      duration: 180,
      coverUrl: 'https://images.unsplash.com/photo-1614613535308-eb5fbd3d2c17',
      audioUrl: 'mock_url_1'
    }
  ];
};
```

### 6.3. Verification Unit Test (`src/tests/example.test.tsx`)
A unit test to verify Vitest and React Testing Library setup:

```typescript
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import React from 'react';

const DummyComponent = () => <div>Aure Music v2</div>;

describe('React Setup Verification', () => {
  it('renders dummy component successfully', () => {
    render(<DummyComponent />);
    expect(screen.getByText('Aure Music v2')).toBeInTheDocument();
  });
});
```

### 6.4. Global Styles Setup (`src/styles/global.css`)
Entry point for Tailwind CSS directives:

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

/* Scrollbar and custom styling hooks can be added here in Milestone 2 */
```

---

## 7. Step-by-Step Recommendations for the Worker

Here is the clean, logical procedure the Implementer Worker should perform to complete Milestone 1:

1. **Scaffold Folder**:
   ```bash
   npm create vite@latest aure-music-v2 -- --template react-ts
   ```
2. **Navigate & Install Packages**:
   ```bash
   cd aure-music-v2
   npm install zustand framer-motion
   npm install -D tailwindcss postcss autoprefixer vitest jsdom @testing-library/react @testing-library/jest-dom @types/react @types/react-dom @types/node prettier eslint-config-prettier
   ```
3. **Configure Tailwind & PostCSS**:
   - Run `npx tailwindcss init -p` to generate initial config files.
   - Replace contents of `tailwind.config.js` and `postcss.config.js` with the draft code provided in Section 4.
4. **Vite, Vitest, and TypeScript Config**:
   - Replace contents of `vite.config.ts` with the draft in Section 4.1.
   - Update `tsconfig.app.json` (or `tsconfig.json`) to include the `@/*` path mapping in `compilerOptions` as detailed in Section 4.7.
5. **Lint & Format Config**:
   - Replace contents of `eslint.config.js` with the flat config in Section 4.4.
   - Create `.prettierrc` and `.prettierignore` in `aure-music-v2/` and populate them with the configs from Sections 4.5 and 4.6.
6. **Structure Folders**:
   - Inside `aure-music-v2/src/`, create directories: `components`, `store`, `api`, `styles`, and `tests`.
7. **Write Boilerplate & Mock Skeletons**:
   - Write the Tailwind CSS directives inside `src/styles/global.css`.
   - Write `src/tests/setup.ts` to include `@testing-library/jest-dom`.
   - Write `src/tests/example.test.tsx` to verify the testing environment.
   - Write the Zustand store interface inside `src/store/playerStore.ts`.
   - Write the Mock API interface inside `src/api/mockApi.ts`.
8. **Clean Boilerplate Files**:
   - Delete `src/App.css` and `src/index.css`.
   - Update `src/main.tsx` to import `./styles/global.css` instead of `./index.css`.
   - Update `src/App.tsx` to remove the import of `./App.css` and display a clean entry UI.
9. **Verify System Integrity**:
   - Run formatting: `npm run format`
   - Run linting check: `npm run lint`
   - Run unit testing suite: `npm test`
   - Run production compilation check: `npm run build`
