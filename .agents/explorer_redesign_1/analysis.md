# AURA Music Frontend Architecture Analysis

This report presents the findings and proposed implementation strategies for the AURA Music redesign, based on an investigation of the frontend codebase (`ui/web_new/`) and its integration with the Python backend.

---

## 1. CSS Theme Architecture & 10-Theme Support

### Observation
- The frontend theme configurations are located in `ui/web_new/css/themes.css` (defining CSS variables for themes) and `ui/web_new/js/settings.js` (rendering the settings theme grid).
- **CSS Variables Defined**: `themes.css` defines `--bg-main`, `--bg-surface`, `--accent`, `--accent-glow`, and `--border-glow` for 10 themes: AMOLED, Dark, Midnight, Emerald, Sunset, Ocean, Lavender, Rose, Amber, and Slate.
- **JavaScript Configuration Mismatch**: `settings.js` contains 17 themes in its `THEMES` array, including unimplemented themes like `aqua`, `light`, `sky`, `mint`, etc.
- **Critical CSS Bug**: Ripgrep/Powershell searches reveal that `styles.css` uses `--primary`, `--primary-rgb`, and `--primary-fg` for active states, gradients, visualizer colors, and buttons, but **these variables are never defined anywhere** in `themes.css` or `styles.css`. This leads to broken or unstyled UI elements when themes change.

### Proposed Solution
1. **Align JavaScript Themes**: Limit the `THEMES` array in `settings.js` to the 10 supported themes.
2. **Correct Theme Dot Colors**: Update the `colors` array for each theme in `settings.js` to match the exact background and accent values defined in `themes.css`.
3. **Map Semantic Variables**: Define the `--primary`, `--primary-rgb`, and `--primary-fg` variables for each theme inside `themes.css` so that the elements automatically inherit the active theme colors.

#### Updated `THEMES` array in `ui/web_new/js/settings.js`:
```javascript
const THEMES = [
    { id: 'amoled', name: 'AMOLED', colors: ['#ffffff', '#000000'] },
    { id: 'dark', name: 'Dark', colors: ['#ffffff', '#121212'] },
    { id: 'midnight', name: 'Midnight', colors: ['#3b82f6', '#0a0e17'] },
    { id: 'emerald', name: 'Emerald', colors: ['#10b981', '#0b1410'] },
    { id: 'sunset', name: 'Sunset', colors: ['#f97316', '#170c0a'] },
    { id: 'ocean', name: 'Ocean', colors: ['#06b6d4', '#06141a'] },
    { id: 'lavender', name: 'Lavender', colors: ['#a855f7', '#130b1c'] },
    { id: 'rose', name: 'Rose', colors: ['#ec4899', '#1a0b12'] },
    { id: 'amber', name: 'Amber', colors: ['#ff9f1c', '#1a120e'] },
    { id: 'slate', name: 'Slate', colors: ['#94a3b8', '#0f172a'] }
];
```

#### Mapping `--primary` Variables in `ui/web_new/css/themes.css`:
```css
/* 1. AMOLED */
:root[data-theme="amoled"] {
    --bg-main: #000000;
    --bg-surface: #0a0a0a;
    --accent: #ffffff;
    --accent-glow: rgba(255, 255, 255, 0.15);
    --border-glow: rgba(255, 255, 255, 0.08);
    --primary: var(--accent);
    --primary-rgb: 255, 255, 255;
    --primary-fg: #000000;
}

/* 2. Dark */
:root[data-theme="dark"] {
    --bg-main: #121212;
    --bg-surface: #1e1e1e;
    --accent: #ffffff;
    --accent-glow: rgba(255, 255, 255, 0.15);
    --border-glow: rgba(255, 255, 255, 0.08);
    --primary: var(--accent);
    --primary-rgb: 255, 255, 255;
    --primary-fg: #000000;
}

/* 3. Midnight */
:root[data-theme="midnight"] {
    --bg-main: #0a0e17;
    --bg-surface: #101622;
    --accent: #3b82f6;
    --accent-glow: rgba(59, 130, 246, 0.15);
    --border-glow: rgba(59, 130, 246, 0.08);
    --primary: var(--accent);
    --primary-rgb: 59, 130, 246;
    --primary-fg: #ffffff;
}

/* 4. Emerald */
:root[data-theme="emerald"] {
    --bg-main: #0b1410;
    --bg-surface: #111f18;
    --accent: #10b981;
    --accent-glow: rgba(16, 185, 129, 0.15);
    --border-glow: rgba(16, 185, 129, 0.08);
    --primary: var(--accent);
    --primary-rgb: 16, 185, 129;
    --primary-fg: #ffffff;
}

/* 5. Sunset */
:root[data-theme="sunset"] {
    --bg-main: #170c0a;
    --bg-surface: #241310;
    --accent: #f97316;
    --accent-glow: rgba(249, 115, 22, 0.15);
    --border-glow: rgba(249, 115, 22, 0.08);
    --primary: var(--accent);
    --primary-rgb: 249, 115, 22;
    --primary-fg: #ffffff;
}

/* 6. Ocean */
:root[data-theme="ocean"] {
    --bg-main: #06141a;
    --bg-surface: #0a2029;
    --accent: #06b6d4;
    --accent-glow: rgba(6, 182, 212, 0.15);
    --border-glow: rgba(6, 182, 212, 0.08);
    --primary: var(--accent);
    --primary-rgb: 6, 182, 212;
    --primary-fg: #ffffff;
}

/* 7. Lavender */
:root[data-theme="lavender"] {
    --bg-main: #130b1c;
    --bg-surface: #1d112b;
    --accent: #a855f7;
    --accent-glow: rgba(168, 85, 247, 0.15);
    --border-glow: rgba(168, 85, 247, 0.08);
    --primary: var(--accent);
    --primary-rgb: 168, 85, 247;
    --primary-fg: #ffffff;
}

/* 8. Rose */
:root[data-theme="rose"] {
    --bg-main: #1a0b12;
    --bg-surface: #26111a;
    --accent: #ec4899;
    --accent-glow: rgba(236, 72, 153, 0.15);
    --border-glow: rgba(236, 72, 153, 0.08);
    --primary: var(--accent);
    --primary-rgb: 236, 72, 153;
    --primary-fg: #ffffff;
}

/* 9. Amber [Default/Active] */
:root[data-theme="amber"], :root {
    --bg-main: #1a120e;
    --bg-surface: #261a15;
    --accent: #ff9f1c;
    --accent-glow: rgba(255, 159, 28, 0.15);
    --border-glow: rgba(255, 159, 28, 0.08);
    --primary: var(--accent);
    --primary-rgb: 255, 159, 28;
    --primary-fg: #000000;
}

/* 10. Slate */
:root[data-theme="slate"] {
    --bg-main: #0f172a;
    --bg-surface: #1e293b;
    --accent: #94a3b8;
    --accent-glow: rgba(148, 163, 184, 0.15);
    --border-glow: rgba(148, 163, 184, 0.08);
    --primary: var(--accent);
    --primary-rgb: 148, 163, 184;
    --primary-fg: #ffffff;
}
```

---

## 2. Custom Styling of Range Sliders & Switch Toggles

### Range Sliders (Volume, Progress)
- **Status**: The volume bar and progress bar are custom divs (`.volume-fill`, `.progress-fill`), not standard HTML `<input type="range">`.
- Since they style their backgrounds using `var(--primary)`, resolving the CSS theme variables issue described in Section 1 automatically aligns their colors to the active theme's accent color.
- **Improvement for Settings Sliders**: For actual `<input type="range" class="slider-input">` elements in settings:
  We can style the track on the left of the thumb to dynamically fill with the accent color using CSS custom properties:
  
  ```css
  /* In styles.css */
  .slider-input {
      -webkit-appearance: none;
      appearance: none;
      width: 100%;
      height: 4px;
      border-radius: 2px;
      background: linear-gradient(to right, var(--primary) 0%, var(--primary) var(--value-percent, 50%), var(--bg-active) var(--value-percent, 50%), var(--bg-active) 100%);
      outline: none;
  }
  ```
  
  ```javascript
  // In settings.js setupSlider()
  slider.addEventListener('input', (e) => {
      const pct = (e.target.value - e.target.min) / (e.target.max - e.target.min) * 100;
      slider.style.setProperty('--value-percent', `${pct}%`);
      if (onChange) onChange(e.target.value);
  });
  ```

### Switch Toggles
- **Status**: Standard checkboxes have already been replaced by `.toggle-switch` elements.
- **Bug**: The `.toggle-switch` background is set to `var(--accent)` (the bright active color) when **off**, and `var(--primary)` when **on**. They look identical in brightness when off and on.
- **Fix**: Style the off-state using a neutral dim color, and the on-state using the active theme's `--primary` (accent) color:

  ```css
  /* In styles.css */
  .toggle-switch {
      width: 40px;
      height: 22px;
      border-radius: 11px;
      background: var(--bg-active); /* Neutral dim color when OFF */
      cursor: pointer;
      position: relative;
      transition: background 0.2s;
      border: 1px solid var(--border);
      padding: 0;
  }
  .toggle-switch.on { 
      background: var(--primary); /* Accent color when ON */
      border-color: transparent;
  }
  ```

---

## 3. Audio Visualizer, Equalizer, & Lyrics Scrolling

### Audio Visualizer (`home-visualizer-canvas`)
- **Status**: The visualizer simulator in `js/visualizer.js` updates bars based on random math triggers when `isPlaying` is true.
- **Reactivity Fix**: To visualizer bars, bind the speed/phases to actual playback progress and state changes:
  1. Add audio amplitude variation: Increase simulation speed and bar height variance proportionally to the current volume level (`getVolume() / 100`).
  2. Transition visualizer colors to the active theme's accent color by ensuring it reads `var(--primary-rgb)` which is resolved now in `themes.css`.
  3. Reset the visualizer to an idle state (calm sine wave) when audio is paused or stopped, rather than clearing completely.

### Audio Equalizer
- **Status**: VLC on the backend (`audio/engine.py`) exposes a 10-band equalizer.
- **Redesign**: Create a simplified **3-Band (Low / Mid / High)** equalizer in the UI that maps to the 10 bands.
- **Mapping Logic**:
  - **Low (Bass)**: Controls VLC bands 0, 1, 2 (31 Hz, 62 Hz, 125 Hz).
  - **Mid (Mids)**: Controls VLC bands 3, 4, 5, 6 (250 Hz, 500 Hz, 1 kHz, 2 kHz).
  - **High (Treble)**: Controls VLC bands 7, 8, 9 (4 kHz, 8 kHz, 16 kHz).
  
  In `js/equalizer.js`, render 3 sliders and update the 10-band array sent to Python:
  ```javascript
  // JavaScript implementation mapping 3 UI bands to 10 VLC bands
  let uiBands = { low: 0, mid: 0, high: 0 };

  function apply3BandEq() {
      let bands = [
          uiBands.low, uiBands.low, uiBands.low,    // Bass (0-2)
          uiBands.mid, uiBands.mid, uiBands.mid, uiBands.mid, // Mids (3-6)
          uiBands.high, uiBands.high, uiBands.high  // Treble (7-9)
      ];
      window.pywebview.api.set_equalizer(eqPreamp, bands);
  }
  ```

### Lyrics Smooth Scrolling View
- **Status**: Lyrics scrolling currently calculates offsets manually and uses `scrollTo({ top: offset, behavior: 'smooth' })`.
- **Bug**: `styles.css` has `scroll-behavior: smooth` on `.lyrics-scroll-container`. Combining CSS `scroll-behavior: smooth` with JS `{ behavior: 'smooth' }` causes double-smoothing, causing lag, stutter, or overshooting in hybrid Edge WebView2 apps.
- **Fix**: Use the standard `scrollIntoView` API which naturally centers elements inside scrollable layouts smoothly:
  ```javascript
  // Replace current scrolling logic in js/lyrics.js
  function updateLyricsPosition(posMs) {
      if (parsedLyrics.length === 0) return;
      let newIndex = -1;
      for (let i = 0; i < parsedLyrics.length; i++) {
          if (posMs >= parsedLyrics[i].timeMs) newIndex = i;
          else break;
      }
      if (newIndex !== currentLineIndex && newIndex !== -1) {
          const content = document.getElementById('lyrics-content');
          const lines = content.querySelectorAll('.lyric-line');
          if (currentLineIndex !== -1 && lines[currentLineIndex]) {
              lines[currentLineIndex].classList.remove('active');
          }
          if (lines[newIndex]) {
              const targetLine = lines[newIndex];
              targetLine.classList.add('active');
              targetLine.scrollIntoView({ behavior: 'smooth', block: 'center' });
          }
          currentLineIndex = newIndex;
      }
  }
  ```

---

## 4. Bug Fixes

### Bug A: PyWebView Native Transparency Issue
- **Observation**: PyWebView's `transparent=True` is overridden and blocked because `#app-container` and `#main-content` have solid background colors (`var(--bg-main)` and `var(--bg-surface)`).
- **Fix**: 
  1. Make the document viewport transparent.
  2. Use CSS `color-mix` to automatically apply an alpha channel to the theme variables, allowing window transparency without modifying color variables directly.
  
  ```css
  /* Add/Adjust in styles.css */
  html, body {
      background: transparent !important;
  }
  
  #app-container {
      display: flex;
      height: 100vh;
      width: 100vw;
      position: relative;
      background-color: color-mix(in srgb, var(--bg-main) 75%, transparent); /* 75% Opacity */
  }
  
  #main-content {
      /* rest remains same */
      background: color-mix(in srgb, var(--bg-surface) 65%, transparent); /* 65% Opacity */
      backdrop-filter: blur(var(--glass-blur));
      -webkit-backdrop-filter: blur(var(--glass-blur));
  }
  ```

### Bug B: Library Playlists Click Handler & `createPlaylist` ID Issue
1. **`createPlaylist` ID Bug**: 
   - **Reason**: In `library.js` line 247, `window.pywebview.api.create_playlist(...)` returns the newly created integer ID (e.g. `5`) directly from Python (`cursor.lastrowid`). 
   - However, `library.js` line 248-249 attempts to access `pl.id`:
     `await window.pywebview.api.add_to_playlist(pl.id, currentContextTrack);`
   - Since `pl` is an integer, `pl.id` is `undefined`. This sends `undefined` to Python, which causes SQLite to fail on a `NOT NULL` constraint and halts JS execution, meaning `loadPlaylists()` is never called.
   - **Fix**: Change `pl.id` to `pl` inside `createPlaylist()`.

2. **Click Handler Bug**:
   - **Reason**: If databases are imported or created on systems where columns are mapped to uppercase keys, `pl.id` is evaluated to `undefined`.
   - **Fix**: Make ID extraction case-insensitive by fallback matching: `pl.id || pl.ID`. Also, replace the dataset reference with `getAttribute` to bypass dataset casing issues.

#### Fixed Functions in `ui/web_new/js/library.js`:
```javascript
export async function createPlaylist() {
    const name = prompt('Введите название нового плейлиста:');
    if (name && name.trim()) {
        try {
            const plId = await window.pywebview.api.create_playlist(name.trim());
            // Fix: plId is the raw integer returned from python db insert
            if (plId && currentContextTrack) {
                await window.pywebview.api.add_to_playlist(plId, currentContextTrack);
            }
        } catch (e) {
            console.error("Failed to add track to new playlist:", e);
        }
        loadPlaylists();
    }
}
```

```javascript
// Inside loadPlaylists() rendering section
playlists.forEach(pl => {
    // Robustness: Support uppercase schema IDs
    const id = pl.id !== undefined ? pl.id : pl.ID;
    html += `
        <div class="card" style="padding:0;overflow:hidden;cursor:pointer" data-pl-id="${id}" data-pl-name="${pl.name}">
            <div style="height:100px;display:flex;align-items:center;justify-content:center;background:var(--accent)">
                <i data-lucide="list-music" style="width:32px;height:32px;color:var(--text-sec)"></i>
            </div>
            <div style="padding:10px">
                <div style="font-size:13px;font-weight:600" class="truncate">${pl.name}</div>
                <div style="font-size:11px;color:var(--text-sec)">${pl.track_count || 0} треков</div>
            </div>
        </div>
    `;
});
```

```javascript
// Inside loadPlaylists() click handler binder section
container.querySelectorAll('[data-pl-id]').forEach(card => {
    card.addEventListener('click', async () => {
        // Robustness: Use getAttribute to prevent casing conversion issues
        const plId = parseInt(card.getAttribute('data-pl-id'));
        const plName = card.getAttribute('data-pl-name');
        
        // Show playlist details view
        document.querySelectorAll('.view-page').forEach(v => v.classList.remove('active'));
        const detailsView = document.getElementById('view-playlist-details');
        if (detailsView) detailsView.classList.add('active');
        
        const titleEl = document.getElementById('pl-details-title');
        if (titleEl) titleEl.textContent = plName;
        
        const tracksContainer = document.getElementById('pl-details-tracks');
        const countEl = document.getElementById('pl-details-count');
        if (tracksContainer) tracksContainer.innerHTML = '<div class="empty-state"><div class="spinner"></div></div>';
        
        try {
            const tracks = await window.pywebview.api.get_playlist_tracks(plId);
            if (countEl) countEl.textContent = `${tracks ? tracks.length : 0} треков`;
            
            if (!tracks || tracks.length === 0) {
                if (tracksContainer) tracksContainer.innerHTML = '<div class="empty-state">В этом плейлисте пока нет треков</div>';
            } else {
                if (tracksContainer) {
                    tracksContainer.innerHTML = '';
                    tracks.forEach((track, i) => {
                        tracksContainer.appendChild(createTrackElement(track, i, tracks, getCurrentTrack()));
                    });
                }
            }
            
            const playBtn = document.getElementById('pl-btn-play');
            if (playBtn) {
                playBtn.onclick = () => {
                    if (tracks && tracks.length > 0) {
                        window.pywebview.api.play_track(tracks[0], tracks);
                    }
                };
            }
            renderIcons();
        } catch (err) {
            console.error(err);
            if (tracksContainer) tracksContainer.innerHTML = '<div class="empty-state text-error">Ошибка загрузки треков</div>';
        }
    });
});
```
