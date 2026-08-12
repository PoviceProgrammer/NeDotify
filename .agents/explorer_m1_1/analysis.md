# Milestone 1 (Project Init) Analysis Report

## Executive Summary
This report analyzes the initialization requirements for Aure Music v2, a React + Vite + TypeScript frontend. It details workspace conflicts, scaffolding methods, NPM package requirements, configuration drafts, and execution steps for the implementation Worker.

---

## 1. Workspace Analysis and File Conflicts

An inspection of the workspace path `c:\Users\valee\OneDrive\Desktop\ждж\дз\AURA Music\` was performed. 

### Existing Directories and Files
The directory contains files related to a Python/Pywebview based application (referred to as Aure Music v1 or NeDotify):
- **Directories**: `.agents`, `.test_runs`, `.venv`, `__pycache__`, `audio`, `backups`, `build`, `core`, `dist`, `services`, `tests`, `ui`, `utils`.
- **Files**: `main.py`, `requirements.txt`, `TEST_READY.md`, `TEST_INFRA.md`, `PROJECT.md`, `settings_logic.js`, `settings_new.html`, and several utility python/javascript script files (`check_braces.py`, `debug_links.py`, `restore_all_js.py`, etc.).

### Conflict Status
- **Target Folder**: `aure-music-v2`
- **Result**: No existing directory or file named `aure-music-v2` exists in the workspace.
- **Conflict Assessment**: There are **no naming conflicts** for scaffolding the new React application under `aure-music-v2`. The implementation Worker can safely create this folder. All legacy assets and files remain separate.

---

## 2. Project Scaffolding Strategy

The frontend will be scaffolded under the subdirectory `aure-music-v2` using the official Vite React-TypeScript template.

### Scaffolding Command
```bash
# From the workspace root:
npm create vite@latest aure-music-v2 -- --template react-ts
```
This initializes a React 18+ app with TypeScript support in a non-interactive way.

### Code Layout Setup
Once the Vite project is scaffolded, the following subdirectories must be created under `aure-music-v2/src/` to align with the layout specified in `PROJECT.md`:
- `src/components/` - Holds all visual React components (Player, Sidebar, Controls, Visualizer, etc.).
- `src/store/` - Holds Zustand store configurations (`usePlayerStore.ts`).
- `src/api/` - Holds mock API client declarations (`mockApi.ts`).
- `src/styles/` - Holds global stylesheet directives, custom scrollbars, and themes.
- `src/tests/` - Holds Vitest and React Testing Library tests.

---

## 3. NPM Package Plan

The project requires specific npm packages for runtime functionality, styling, state management, animations, and testing.

### Runtime / Production Dependencies
- **`zustand`**: State management library for player states, transparency toggle, and themes.
- **`framer-motion`**: Animation library for transition effects.
- **`react`** & **`react-dom`**: React core library (scaffolded by default).

### Development Dependencies
- **Styling**: `tailwindcss`, `postcss`, `autoprefixer`.
- **Testing**: `vitest`, `jsdom`, `@testing-library/react`, `@testing-library/jest-dom`, `@testing-library/user-event`.
- **Linting & Formatting**: `eslint`, `prettier`, `eslint-config-prettier`, `eslint-plugin-react`, `eslint-plugin-react-hooks`, `eslint-plugin-react-refresh`, `@typescript-eslint/eslint-plugin`, `@typescript-eslint/parser`, `globals`, `@eslint/js`, `typescript-eslint`.
- **Type Definitions**: `@types/react`, `@types/react-dom`, `@types/node` (needed for Node path resolving in configuration files).

### Installation Commands
```bash
# 1. Navigate to the scaffolded directory
cd aure-music-v2

# 2. Install Runtime Dependencies
npm install zustand framer-motion

# 3. Install Development Dependencies
npm install -D tailwindcss postcss autoprefixer vitest jsdom @testing-library/react @testing-library/jest-dom @testing-library/user-event eslint eslint-config-prettier eslint-plugin-react eslint-plugin-react-hooks eslint-plugin-react-refresh prettier @types/react @types/react-dom @types/node typescript-eslint @eslint/js globals
```

---

## 4. Configuration File Drafts

To ensure the project compiles and tests execute cleanly, the following configurations must be established in the `aure-music-v2` root.

### A. Vite Configuration (`vite.config.ts`)
Configured to support React compilation and the `@/` absolute import alias pointing to the `src` directory.

```typescript
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
  server: {
    port: 3000,
    open: true,
  },
});
```

### B. Vitest Configuration (`vitest.config.ts`)
Configured to run Vitest using `jsdom` environment and execute the setup file for Testing Library matchers.

```typescript
/// <reference types="vitest" />
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/tests/setup.ts',
    css: true,
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
});
```

### C. Testing Setup File (`src/tests/setup.ts`)
Extends Vitest's `expect` with `@testing-library/jest-dom` assertion matchers (e.g. `toBeInTheDocument`).

```typescript
import '@testing-library/jest-dom/vitest';
```

### D. Tailwind CSS Configuration (`tailwind.config.js`)
Configured to scan files in HTML and React files.

```javascript
/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      // Extended themes and variables will be added in Milestone 2
    },
  },
  plugins: [],
}
```

### E. PostCSS Configuration (`postcss.config.js`)
Integrates Tailwind CSS and Autoprefixer with the Vite builder.

```javascript
export default {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
}
```

### F. ESLint Flat Configuration (`eslint.config.js`)
Configured using the modern Flat Configuration standard (used in newer Vite versions). Includes Prettier integration to prevent layout rules conflicting with ESLint.

```javascript
import js from '@eslint/js';
import globals from 'globals';
import reactHooks from 'eslint-plugin-react-hooks';
import reactRefresh from 'eslint-plugin-react-refresh';
import tseslint from 'typescript-eslint';
import eslintConfigPrettier from 'eslint-config-prettier';

export default tseslint.config(
  { ignores: ['dist', 'node_modules', 'coverage'] },
  {
    extends: [
      js.configs.recommended,
      ...tseslint.configs.recommended,
      eslintConfigPrettier,
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
    },
  }
);
```

*(Note: If the legacy ESLint configuration `.eslintrc.json` is scaffolded instead, use the following configuration content:)*
```json
{
  "root": true,
  "env": {
    "browser": true,
    "es2020": true
  },
  "extends": [
    "eslint:recommended",
    "plugin:@typescript-eslint/recommended",
    "plugin:react-hooks/recommended",
    "prettier"
  ],
  "ignorePatterns": ["dist", ".eslintrc.cjs", "node_modules"],
  "parser": "@typescript-eslint/parser",
  "plugins": ["react-refresh"],
  "rules": {
    "react-refresh/only-export-components": [
      "warn",
      { "allowConstantExport": true }
    ]
  }
}
```

### G. Prettier Configuration (`.prettierrc`)
Defines strict formatting rules.

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

### H. Prettier Ignore Configuration (`.prettierignore`)
```
dist
node_modules
coverage
```

### I. TypeScript Configuration Adjustments (`tsconfig.app.json`)
The `tsconfig.app.json` file needs to include configuration for Vite's path resolution alias and Vitest global types.

```json
{
  "compilerOptions": {
    "composite": true,
    "tsBuildInfoFile": "./node_modules/.tmp/tsconfig.app.tsbuildinfo",
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["DOM", "DOM.Iterable", "ES2020"],
    "module": "ESNext",
    "skipLibCheck": true,

    /* Bundler mode */
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",

    /* Linting */
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,

    /* Path Aliasing and Vitest Globals */
    "baseUrl": ".",
    "paths": {
      "@/*": ["./src/*"]
    },
    "types": ["vite/client", "vitest/globals"]
  },
  "include": ["src"]
}
```

And update the main `tsconfig.json` to ensure compiler options are synced:
```json
{
  "files": [],
  "references": [
    { "path": "./tsconfig.app.json" },
    { "path": "./tsconfig.node.json" }
  ]
}
```

---

## 5. Package.json Scripts

The `package.json` must be updated with the following core scripts to compile, lint, and test the code successfully.

```json
"scripts": {
  "dev": "vite",
  "build": "tsc && vite build",
  "lint": "eslint . --max-warnings 0",
  "lint:fix": "eslint . --fix",
  "format": "prettier --write \"src/**/*.{ts,tsx,css,md}\"",
  "test": "vitest run",
  "test:watch": "vitest"
}
```

---

## 6. Implementation Step-by-Step Recommendations for the Worker

The implementer must execute the following actions sequentially to successfully complete Milestone 1:

### Phase 1: Project Setup and Dependencies
1. **Navigate to the Project Directory:**
   ```bash
   cd c:\Users\valee\OneDrive\Desktop\ждж\дз\AURA Music
   ```
2. **Scaffold React Vite Application:**
   ```bash
   npm create vite@latest aure-music-v2 -- --template react-ts
   ```
3. **Change Directory:**
   ```bash
   cd aure-music-v2
   ```
4. **Install Runtime Libraries:**
   ```bash
   npm install zustand framer-motion
   ```
5. **Install Development Tools:**
   ```bash
   npm install -D tailwindcss postcss autoprefixer vitest jsdom @testing-library/react @testing-library/jest-dom @testing-library/user-event eslint eslint-config-prettier eslint-plugin-react eslint-plugin-react-hooks eslint-plugin-react-refresh prettier @types/react @types/react-dom @types/node typescript-eslint @eslint/js globals
   ```
6. **Initialize Tailwind CSS:**
   ```bash
   npx tailwindcss init -p
   ```

### Phase 2: Configuration Files
7. **Overwrite Configurations:**
   - Overwrite `vite.config.ts` with the absolute import resolution configuration.
   - Create `vitest.config.ts` in the root folder.
   - Overwrite `tailwind.config.js` and `postcss.config.js` with correct contents.
   - Create `.prettierrc` and `.prettierignore`.
   - Update `eslint.config.js` (or `.eslintrc.json`) to integrate TypeScript and Prettier configurations.
   - Update `tsconfig.app.json` with the path alias `@/*` and target type declarations (`vitest/globals`).

### Phase 3: Directory Structure and Sanity Code
8. **Create Folder Layout:**
   - Create directories: `src/components`, `src/store`, `src/api`, `src/styles`, `src/tests`.
9. **Configure Tailwind directives:**
   - Rename `src/index.css` to `src/styles/global.css`.
   - Populate `src/styles/global.css` with the Tailwind directives:
     ```css
     @tailwind base;
     @tailwind components;
     @tailwind utilities;
     ```
   - Update `src/main.tsx` to reference `./styles/global.css` instead of `./index.css` or `./App.css`.
10. **Establish Test Infrastructure:**
    - Create `src/tests/setup.ts` containing the `@testing-library/jest-dom/vitest` import.
    - Create a basic App test `src/tests/App.test.tsx` to verify Vitest works:
      ```tsx
      import { render, screen } from '@testing-library/react';
      import { describe, it, expect } from 'vitest';
      import App from '../App';

      describe('App Component Sanity Check', () => {
        it('renders without crashing', () => {
          render(<App />);
          // In default Vite template, App displays "Vite + React" or count buttons
          const headings = screen.getAllByRole('heading');
          expect(headings.length).toBeGreaterThan(0);
        });
      });
      ```

### Phase 4: Validation
11. **Edit scripts** in `package.json` to include standard build, lint, and test scripts.
12. **Execute Validation Commands:**
    - Run lint check: `npm run lint`
    - Run unit tests: `npm run test` (confirm it runs in CI/headless mode, passing 100%)
    - Run build process: `npm run build` (verify that TypeScript and Vite compile without errors into the `dist` folder)
