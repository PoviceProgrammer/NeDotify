/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        themeBg: 'var(--bg-color)',
        themeText: 'var(--text-color)',
        themeAccent: 'var(--accent-color)',
        themeAccentHover: 'var(--accent-hover)',
        themeSidebar: 'var(--sidebar-bg)',
        themeControls: 'var(--controls-bg)',
      },
    },
  },
  plugins: [],
}
