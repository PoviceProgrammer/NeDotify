# Analysis Report: Aure Music v2 Project Init (Milestone 1)

This report details the scaffolding, package planning, configuration files, scripts, and step-by-step implementation recommendations for the initialization of Aure Music v2.

---

## 1. Workspace Assessment & Conflicts

An investigation of the current workspace (`c:\Users\valee\OneDrive\Desktop\ждж\дз\AURA Music\`) was conducted:
- **No Existing Project Directory**: There is no folder named `aure-music-v2` in the root.
- **No Pre-existing Config Conflicts**: No files like `tailwind.config.js`, `postcss.config.js`, `tsconfig.json` exist in the root folder that would collide with the new frontend app structure.
- **Backend Infrastructure Presence**: Files such as `main.py`, `core/`, `tests/` contain the Python NeDotify backend code. The React frontend should reside entirely within `aure-music-v2/` to ensure full boundary isolation between frontend (Tauri-ready React) and backend code.

---

## 2. Frontend Scaffolding Plan

To scaffold the React + Vite + TypeScript application:
1. Open terminal inside the workspace directory (`c:\Users\valee\OneDrive\Desktop\ждж\дз\AURA Music\`).
2. Run the Vite creation tool targeting the new directory name `aure-music-v2` using the React-TS template:
   ```powershell
   npm create vite@latest aure-music-v2 -- --template react-ts
   ```
3. Move into the directory:
   ```powershell
   cd aure-music-v2
   ```

---

## 3. Package Installation Plan

The project requires several packages for styling, state management, animations, and testing.

### Production Dependencies
Install standard runtime dependencies:
```powershell
npm install framer-motion zustand
```
- **framer-motion**: Controls fluid layout transitions and animations for player controls and sidebar overlays.
- **zustand**: Powers the global player store (`isTransparencyEnabled`, `theme`, queue playback, tracks, and volume).

### Development Dependencies
Install packages needed for build, formatting, linting, and testing:
```powershell
npm install -D tailwindcss postcss autoprefixer vitest jsdom @testing-library/react @testing-library/jest-dom @testing-library/user-event @types/node
```
- **tailwindcss postcss autoprefixer**: Styling pipeline (Tailwind CSS v3 configuration).
- **vitest**: Lightning-fast Vite-native testing framework.
- **jsdom**: Simulates a web browser DOM environment inside Node.js for tests.
- **@testing-library/react**: Utilities for rendering React components and asserting DOM changes in tests.
- **@testing-library/jest-dom**: Offers custom matchers (`toBeInTheDocument`, etc.) to simplify assertions.
- **@testing-library/user-event**: Simulates browser user-interactions (clicks, keystrokes).
- **@types/node**: Provides Node type definitions to resolve path mapping (`__dirname` / `path`) inside configs.

---

## 4. Draft Configuration Files

Below are the drafted configuration files which the Worker should write to the project.

### 4.1. Vite Configuration (`aure-music-v2/vite.config.ts`)
Needs to resolve path alias `@/*` to `./src/*` and set up Vitest options.
```typescript
/// <reference types="vitest" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/tests/setup.ts',
    css: true,
  },
})
```

### 4.2. Tailwind & PostCSS Configuration

#### `aure-music-v2/tailwind.config.js`
Tailwind CSS configuration targeting the Vite app entries.
```javascript
/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      // Future themes configuration can be added here
    },
  },
  plugins: [],
}
```

#### `aure-music-v2/postcss.config.js`
Enables tailwindcss and autoprefixer plugins in the PostCSS pipeline.
```javascript
export default {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
}
```

### 4.3. ESLint & Prettier Configuration

#### `aure-music-v2/eslint.config.js`
Flat ESLint configuration format matching modern Vite configurations:
```javascript
import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'

export default tseslint.config(
  { ignores: ['dist'] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
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
  },
)
```

#### `aure-music-v2/.prettierrc`
Configuration for code formatting:
```json
{
  "semi": false,
  "tabWidth": 2,
  "singleQuote": true,
  "trailingComma": "all",
  "printWidth": 80
}
```

### 4.4. Test Setup Configuration (`aure-music-v2/src/tests/setup.ts`)
Loads DOM assertions to make them globally available during tests.
```typescript
import '@testing-library/jest-dom'
```

---

## 5. package.json Scripts

The `scripts` block in `aure-music-v2/package.json` must be defined as follows to ensure compatibility with standard workflow verification steps:

```json
"scripts": {
  "dev": "vite",
  "build": "tsc && vite build",
  "lint": "eslint .",
  "test": "vitest run",
  "test:watch": "vitest",
  "preview": "vite preview"
}
```

- `npm run build`: Compiles TS checking first (`tsc`), then builds the optimized client bundle.
- `npm run lint`: Analyzes style/code issues across the codebase.
- `npm test` or `npm run test`: Executes Vitest tests in single-run CI/CD mode (useful for verification gates).

---

## 6. Step-by-Step Scaffolding & Setup Guide for the Implementer

The Worker agent should perform the following actions:

1. **Scaffold the App**:
   Run `npm create vite@latest aure-music-v2 -- --template react-ts` from the root (`c:\Users\valee\OneDrive\Desktop\ждж\дз\AURA Music\`).
2. **Move Directory & Install Dependencies**:
   `cd aure-music-v2` and run:
   - `npm install framer-motion zustand`
   - `npm install -D tailwindcss postcss autoprefixer vitest jsdom @testing-library/react @testing-library/jest-dom @testing-library/user-event @types/node`
3. **Overwrite Config Files**:
   Create or overwrite these configuration files with the contents listed above in Section 4:
   - `vite.config.ts`
   - `tailwind.config.js`
   - `postcss.config.js`
   - `eslint.config.js`
   - `.prettierrc`
4. **Setup TypeScript Paths**:
   Modify `tsconfig.app.json` (and `tsconfig.json` if needed) to map `@/*` to `./src/*` so paths align correctly. Also include `"types": ["vitest/globals"]` in compiler options.
5. **Configure Tailwind directives inside CSS**:
   Add the following directives to the top of `src/index.css` (or replacement global styling file):
   ```css
   @tailwind base;
   @tailwind components;
   @tailwind utilities;
   ```
6. **Restructure Directory Layout**:
   Create the required folder structure specified in `PROJECT.md`:
   - `src/components/`
   - `src/store/`
   - `src/api/`
   - `src/styles/`
   - `src/tests/`
   Move standard CSS files into `src/styles/` if preferred, updating corresponding imports in `src/main.tsx`.
7. **Write an Initial Test**:
   Create `src/tests/App.test.tsx` to verify setup works properly:
   ```typescript
   import { render, screen } from '@testing-library/react'
   import App from '../App'

   test('renders Vite + React header', () => {
     render(<App />)
     expect(screen.getByText(/Vite \+ React/i)).toBeInTheDocument()
   })
   ```
8. **Verify Verification Runs**:
   Run the scripts to check they all pass cleanly:
   - `npm run lint`
   - `npm run build`
   - `npm test`
