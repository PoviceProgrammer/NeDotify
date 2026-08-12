import React from 'react';
import { usePlayerStore } from '../store/usePlayerStore';

const THEMES = [
  'aura-dark', 'aura-light', 'neon-purple', 'cyberpunk', 'glass-morph',
  'sunset-glow', 'ocean-breeze', 'forest-mist', 'royal-gold', 'crimson-tide',
  'monochrome', 'matrix-green', 'pastel-pink', 'solar-flare', 'deep-space',
  'nordic-frost', 'vintage-sepia'
];

export const Sidebar: React.FC = () => {
  const {
    theme,
    setTheme,
    isTransparencyEnabled,
    setTransparencyEnabled
  } = usePlayerStore();

  return (
    <aside
      data-testid="sidebar"
      className="no-scrollbar"
      style={{
        width: '260px',
        borderRight: '1px solid rgba(255, 255, 255, 0.1)',
        padding: '1.5rem',
        display: 'flex',
        flexDirection: 'column',
        gap: '1.5rem',
        backgroundColor: 'var(--sidebar-bg)',
        overflowY: 'auto',
        transition: 'all 0.3s ease'
      }}
    >
      <div>
        <h3 style={{ fontSize: '1.1rem', fontWeight: 'bold', marginBottom: '0.75rem' }}>Navigation</h3>
        <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
          <li style={{ cursor: 'pointer', padding: '0.25rem 0' }}>Home</li>
          <li style={{ cursor: 'pointer', padding: '0.25rem 0' }}>Library</li>
          <li style={{ cursor: 'pointer', padding: '0.25rem 0' }}>Playlists</li>
        </ul>
      </div>

      <div>
        <h4 style={{ fontSize: '0.95rem', fontWeight: 'bold', marginBottom: '0.75rem' }}>Theme Swatches</h4>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '0.4rem' }}>
          {THEMES.map((t) => (
            <button
              key={t}
              data-testid={`theme-swatch-${t}`}
              onClick={() => setTheme(t)}
              style={{
                padding: '0.35rem 0.5rem',
                border: '1px solid rgba(255, 255, 255, 0.15)',
                background: theme === t ? 'var(--accent-color)' : 'rgba(255, 255, 255, 0.05)',
                color: theme === t ? '#fff' : 'var(--text-color)',
                cursor: 'pointer',
                borderRadius: '6px',
                fontSize: '0.7rem',
                textAlign: 'center',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                transition: 'all 0.2s ease'
              }}
            >
              {t.replace('-', ' ')}
            </button>
          ))}
        </div>
      </div>

      <div style={{ marginTop: 'auto', borderTop: '1px solid rgba(255, 255, 255, 0.1)', paddingTop: '1rem' }}>
        <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer', fontSize: '0.85rem' }}>
          <input
            type="checkbox"
            data-testid="transparency-toggle"
            checked={!!isTransparencyEnabled}
            onChange={(e) => setTransparencyEnabled(e.target.checked)}
            style={{ cursor: 'pointer' }}
          />
          Enable Transparency
        </label>
      </div>
    </aside>
  );
};
